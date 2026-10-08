"""Module 3 — technical + content signal analyzer.

Rule-based checks producing a 0-100 technical score. Weights are declared in a
single constants dict so they're easy to explain and adjust.
"""

import re
from typing import Any, Dict, List

# Each check contributes a weighted point value. Weights sum to 100.
WEIGHTS: Dict[str, float] = {
    "meta_description": 15.0,      # present and reasonable length
    "schema_data": 20.0,          # >=1 JSON-LD schema.org block
    "single_h1": 12.0,            # exactly one <h1>
    "heading_hierarchy": 8.0,     # sensible structure below h1
    "alt_coverage": 10.0,         # image alt-text coverage
    "word_count": 10.0,           # enough substantive content
    "statistics": 10.0,           # numerical statistics in body
    "quotations": 7.0,            # direct quotes present
    "outbound_citations": 8.0,    # links to external authoritative domains
}

# Tuning thresholds.
META_MIN, META_IDEAL_LOW, META_IDEAL_HIGH, META_MAX = 50, 120, 160, 320
ALT_COVERAGE_THRESHOLD = 0.80
MIN_WORD_COUNT = 300

# Regex for numeric statistics: a number followed by %, a unit, or a magnitude
# word, or a standalone large number embedded in text.
_STAT_PATTERN = re.compile(
    r"\b\d[\d,\.]*\s?(?:%|percent|million|billion|thousand|k\b|x\b|"
    r"kg|km|mb|gb|tb|ms|hrs?|hours?|days?|years?|\$|usd|eur)",
    re.IGNORECASE,
)
_PERCENT_OR_CURRENCY = re.compile(r"(?:\d[\d,\.]*\s?%|[$€£]\s?\d[\d,\.]*)")
_QUOTE_PATTERN = re.compile(r"[\"\u201c\u201d\u2018\u2019].{10,}?[\"\u201c\u201d\u2018\u2019]")


def _score_meta(meta: str | None) -> float:
    if not meta:
        return 0.0
    length = len(meta)
    if META_IDEAL_LOW <= length <= META_IDEAL_HIGH:
        return WEIGHTS["meta_description"]
    if META_MIN <= length <= META_MAX:
        return WEIGHTS["meta_description"] * 0.6
    return WEIGHTS["meta_description"] * 0.3


def _score_headings(headings: Dict[str, List[str]]) -> Dict[str, Any]:
    h1 = [h for h in headings.get("h1", []) if h]
    h2 = [h for h in headings.get("h2", []) if h]
    h3 = [h for h in headings.get("h3", []) if h]
    h1_count = len(h1)

    single_h1_pts = WEIGHTS["single_h1"] if h1_count == 1 else (
        WEIGHTS["single_h1"] * 0.3 if h1_count > 1 else 0.0
    )

    # Sensible hierarchy: at least one h1 and some h2s below it; h3 without h2
    # is a weak signal.
    if h1_count >= 1 and len(h2) >= 1:
        hierarchy_pts = WEIGHTS["heading_hierarchy"]
    elif h1_count >= 1 and len(h3) >= 1:
        hierarchy_pts = WEIGHTS["heading_hierarchy"] * 0.4
    else:
        hierarchy_pts = 0.0

    return {
        "h1_count": h1_count,
        "single_h1_pts": single_h1_pts,
        "hierarchy_pts": hierarchy_pts,
        "structure": {"h1": len(h1), "h2": len(h2), "h3": len(h3)},
    }


def detect_content_signals(body_text: str) -> Dict[str, bool]:
    text = body_text or ""
    has_statistics = bool(_STAT_PATTERN.search(text) or _PERCENT_OR_CURRENCY.search(text))
    has_quotations = bool(_QUOTE_PATTERN.search(text))
    return {"has_statistics": has_statistics, "has_quotations": has_quotations}


def analyze(scraped: Dict[str, Any]) -> Dict[str, Any]:
    """Produce technical results + a 0-100 technical score from scraped data."""
    meta = scraped.get("meta_description")
    schema_types = scraped.get("schema_types", []) or []
    headings = scraped.get("headings", {}) or {}
    alt_coverage = float(scraped.get("alt_coverage", 0.0))
    word_count = int(scraped.get("word_count", 0))
    external_links = int(scraped.get("external_link_count", 0))
    body_text = scraped.get("body_text", "")

    # --- individual check scores ---
    meta_pts = _score_meta(meta)

    has_schema = len(schema_types) > 0
    schema_pts = WEIGHTS["schema_data"] if has_schema else 0.0

    heading_info = _score_headings(headings)

    if alt_coverage >= ALT_COVERAGE_THRESHOLD:
        alt_pts = WEIGHTS["alt_coverage"]
    else:
        alt_pts = WEIGHTS["alt_coverage"] * alt_coverage

    if word_count >= MIN_WORD_COUNT:
        word_pts = WEIGHTS["word_count"]
    else:
        word_pts = WEIGHTS["word_count"] * (word_count / MIN_WORD_COUNT)

    signals = detect_content_signals(body_text)
    stats_pts = WEIGHTS["statistics"] if signals["has_statistics"] else 0.0
    quote_pts = WEIGHTS["quotations"] if signals["has_quotations"] else 0.0

    has_outbound = external_links > 0
    citation_pts = WEIGHTS["outbound_citations"] if has_outbound else 0.0

    technical_score = round(
        meta_pts
        + schema_pts
        + heading_info["single_h1_pts"]
        + heading_info["hierarchy_pts"]
        + alt_pts
        + word_pts
        + stats_pts
        + quote_pts
        + citation_pts,
        2,
    )

    print(
        f"[content] technical_score={technical_score} "
        f"(schema={has_schema}, h1={heading_info['h1_count']}, "
        f"alt={alt_coverage:.0%}, words={word_count}, "
        f"stats={signals['has_statistics']}, quotes={signals['has_quotations']}, "
        f"citations={has_outbound})"
    )

    return {
        "meta_description": meta,
        "has_schema_data": has_schema,
        "schema_types": schema_types,
        "h1_count": heading_info["h1_count"],
        "heading_structure": heading_info["structure"],
        "word_count": word_count,
        "has_statistics": signals["has_statistics"],
        "has_quotations": signals["has_quotations"],
        "has_outbound_citations": has_outbound,
        "technical_score": technical_score,
        # extra detail for recommendations (not persisted columns, but useful)
        "alt_coverage": round(alt_coverage, 4),
        "external_link_count": external_links,
    }
