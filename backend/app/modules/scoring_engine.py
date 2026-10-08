"""Module 6 — scoring & recommendation engine.

Combines four signals into a composite 0-100 score and generates a ranked list
of recommendations. Every recommendation is traceable to a specific stored
result — no generic filler.

Composite weights (documented as named constants):
    access    25%
    technical 30%
    mention   30%
    retrieval 15%  (redistributed when Exa is unavailable)

Access sub-score weights bot categories differently: blocking a search/
retrieval bot hurts far more than blocking a training-only bot, because search
bots are what make a page answerable in AI results.
"""

import uuid
from typing import Any, Dict, List, Optional

# --- composite weights ----------------------------------------------------
# AI visibility is the whole point of this tool, so the mention signal carries
# the most weight. Technical/access are enablers, not proof of visibility — a
# perfectly-built page for an unknown brand should still score low.
COMPOSITE_WEIGHTS: Dict[str, float] = {
    "access": 0.15,
    "technical": 0.20,
    "mention": 0.50,
    "retrieval": 0.15,
}

# --- access sub-score: penalty per blocked bot by category ----------------
# Access starts at 100 and loses points for each blocked bot.
ACCESS_PENALTY_PER_BLOCK: Dict[str, float] = {
    "search": 25.0,   # highest impact — kills AI answer visibility
    "user": 15.0,     # user-triggered fetches (e.g. "browse this page")
    "training": 6.0,  # lowest — blocking training != blocking answers
    "unknown": 5.0,
}


def _access_score(bot_rules: Dict[str, Dict[str, Any]]) -> float:
    score = 100.0
    for info in bot_rules.values():
        if not info.get("allowed", True):
            score -= ACCESS_PENALTY_PER_BLOCK.get(info.get("category", "unknown"), 5.0)
    return max(0.0, round(score, 2))


def _mention_score(mention: Optional[Dict[str, Any]]) -> float:
    """Score genuine AI visibility with a strict curve.

    Philosophy (stricter): a high score requires BOTH that the model genuinely
    knows the brand AND that it surfaces the brand organically (unprompted) for
    category queries. Merely being "known" when asked by name is table stakes,
    not strong visibility — so knowledge alone earns only a modest score, while
    organic discovery is what drives the score up.

    Curve:
      - unknown            -> hard cap 8   (model doesn't know it)
      - hallucinated       -> hard cap 20  (model guesses / invents)
      - known, 0% organic  -> ~35          (recognized by name only)
      - known, high organic-> up to 100    (genuinely visible)
    """
    if not mention:
        return 0.0

    brand_known = mention.get("brand_known", "unknown")
    unbranded = float(mention.get("unbranded_mention_rate", 0.0))

    if brand_known == "unknown":
        return round(min(unbranded * 100.0, 8.0), 2)
    if brand_known == "hallucinated":
        return round(min(unbranded * 100.0, 20.0), 2)

    # brand_known == "known":
    # Base of 35 for being genuinely recognized, plus a steep reward for
    # organic discoverability. Discovery is applied on a mild concave curve so
    # partial discovery (e.g. 1/9 lists) doesn't over-reward.
    knowledge_base = 35.0
    discovery_component = (unbranded ** 0.85) * 65.0  # 0..65
    return round(min(knowledge_base + discovery_component, 100.0), 2)


def _retrieval_score(retrieval: Optional[Dict[str, Any]]) -> Optional[float]:
    """Return a 0-100 retrieval score, or None if the signal is unavailable.

    Combines two signals across the query panel:
      - best rank achieved (position quality)
      - retrieval rate (how many of the queries surfaced the page at all)
    """
    if not retrieval or not retrieval.get("available"):
        return None

    best_rank = retrieval.get("best_rank")
    if best_rank is None:
        # Fall back to legacy single-rank field if present.
        best_rank = retrieval.get("retrieved_rank")
    if best_rank is None:
        return 0.0

    # Rank quality: rank 1 -> 100, rank 10 -> ~10 (linear decay).
    rank_score = max(10.0, 100.0 - (best_rank - 1) * 10.0)

    # Coverage: fraction of queries that retrieved the page at all.
    rate = retrieval.get("retrieval_rate")
    if rate is None:
        return round(rank_score, 2)

    # Weight rank quality 65%, coverage 35%.
    return round(rank_score * 0.65 + (float(rate) * 100.0) * 0.35, 2)


def compute_composite(
    access_score: float,
    technical_score: float,
    mention_score: float,
    retrieval_score: Optional[float],
) -> float:
    """Weighted composite. If retrieval is unavailable, its weight is
    redistributed proportionally across the other three signals."""
    weights = dict(COMPOSITE_WEIGHTS)
    components = {
        "access": access_score,
        "technical": technical_score,
        "mention": mention_score,
    }
    if retrieval_score is not None:
        components["retrieval"] = retrieval_score
    else:
        # redistribute retrieval weight across the rest
        retrieval_w = weights.pop("retrieval")
        total_rest = sum(weights[k] for k in components)
        for k in components:
            weights[k] += retrieval_w * (weights[k] / total_rest)

    composite = sum(components[k] * weights[k] for k in components)
    return round(composite, 2)


# --- recommendation generation -------------------------------------------

def _rec(category: str, severity: str, description: str) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "category": category,
        "severity": severity,
        "description": description,
    }


def generate_recommendations(
    access: Optional[Dict[str, Any]],
    technical: Optional[Dict[str, Any]],
    mention: Optional[Dict[str, Any]],
    retrieval: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []

    # --- access ---
    if access:
        bot_rules = access.get("bot_rules", {})
        blocked_search = [b for b, i in bot_rules.items()
                          if i.get("category") == "search" and not i.get("allowed", True)]
        blocked_user = [b for b, i in bot_rules.items()
                        if i.get("category") == "user" and not i.get("allowed", True)]
        blocked_training = [b for b, i in bot_rules.items()
                            if i.get("category") == "training" and not i.get("allowed", True)]

        if blocked_search:
            recs.append(_rec(
                "access", "high",
                f"Search/retrieval bots are blocked in robots.txt: {', '.join(blocked_search)}. "
                "These are the crawlers that let AI assistants cite your page in answers. "
                "Unblocking them is the single highest-impact access fix."
            ))
        if blocked_user:
            recs.append(_rec(
                "access", "medium",
                f"User-triggered fetch bots are blocked: {', '.join(blocked_user)}. "
                "These fire when a user explicitly asks an assistant to read your page; "
                "blocking them prevents on-demand retrieval of your content."
            ))
        if blocked_training:
            recs.append(_rec(
                "access", "low",
                f"Training bots are blocked: {', '.join(blocked_training)}. "
                "This is often an intentional data-rights choice and does NOT stop your "
                "page from appearing in AI answers — search/retrieval bots handle that. "
                "Only unblock these if you want your content used for model training."
            ))
        if not access.get("robots_txt_found"):
            recs.append(_rec(
                "access", "low",
                "No robots.txt was found. AI crawlers default to allowed, which is fine, "
                "but adding an explicit robots.txt lets you control access intentionally."
            ))
        if not access.get("llms_txt_found"):
            recs.append(_rec(
                "access", "low",
                "No llms.txt was found. This is an emerging, non-standard convention — "
                "not required, but adding one can help AI systems find your key content."
            ))

    # --- technical ---
    if technical:
        meta = technical.get("meta_description")
        if not meta:
            recs.append(_rec("technical", "high",
                "No meta description found. Add one (120-160 chars) — it's a primary "
                "summary signal for machine parsing and answer snippets."))
        elif not (120 <= len(meta) <= 160):
            recs.append(_rec("technical", "low",
                f"Meta description is {len(meta)} chars. Aim for 120-160 for ideal snippet coverage."))

        if not technical.get("has_schema_data"):
            recs.append(_rec("technical", "high",
                "No JSON-LD schema.org structured data found. Adding schema (e.g. Organization, "
                "Product, or Article) is one of the strongest machine-readability signals."))

        h1 = technical.get("h1_count", 0)
        if h1 == 0:
            recs.append(_rec("technical", "high",
                "Page has no <h1>. Add exactly one <h1> describing the page's main topic."))
        elif h1 > 1:
            recs.append(_rec("technical", "medium",
                f"Page has {h1} <h1> tags. Use exactly one <h1> and demote the rest to <h2>."))

        if technical.get("alt_coverage", 1.0) < 0.80 and technical.get("word_count", 0) >= 0:
            recs.append(_rec("technical", "low",
                f"Image alt-text coverage is {technical.get('alt_coverage', 0):.0%}. "
                "Add descriptive alt text to reach >80% for accessibility and machine parsing."))

        if technical.get("word_count", 0) < 300:
            recs.append(_rec("technical", "medium",
                f"Body content is thin ({technical.get('word_count', 0)} words). "
                "Substantive content (300+ words) gives AI systems more to cite."))

        if not technical.get("has_statistics"):
            recs.append(_rec("technical", "low",
                "No numerical statistics detected in the body. Concrete figures (percentages, "
                "counts, dates) are highly citable by AI answer engines."))
        if not technical.get("has_quotations"):
            recs.append(_rec("technical", "low",
                "No direct quotations detected. Quotable statements improve the odds of being "
                "cited verbatim in AI answers."))
        if not technical.get("has_outbound_citations"):
            recs.append(_rec("technical", "low",
                "No outbound links to external domains found. Citing authoritative sources is a "
                "trust signal for AI systems."))

    # --- mention (AI visibility) ---
    if mention:
        brand_known = mention.get("brand_known", "unknown")
        unbranded = mention.get("unbranded_mention_rate", 0.0)
        consistency = mention.get("knowledge_consistency", 0.0)

        if brand_known == "unknown":
            recs.append(_rec("mention", "high",
                "The AI model has no reliable knowledge of this brand — when asked "
                "directly, it repeatedly stated it does not recognize it. The brand is "
                "effectively invisible to AI answers. Build authoritative, crawlable "
                "content (Wikipedia, press coverage, structured 'about' pages, consistent "
                "NAP/entity data) so models can learn who the brand is."))
        elif brand_known == "hallucinated":
            recs.append(_rec("mention", "high",
                f"The AI model does NOT genuinely know this brand — it produced "
                f"inconsistent, contradictory descriptions across repeated queries "
                f"(consistency={consistency:.0%}). This is hallucination, not visibility. "
                "Establish a clear, consistent public identity (official entity markup, "
                "authoritative third-party references) so the model stops guessing."))
        else:  # known
            recs.append(_rec("mention", "low",
                f"The AI model genuinely and consistently knows this brand "
                f"(consistency={consistency:.0%}). Strong knowledge grounding — maintain it."))

        if brand_known != "unknown" and unbranded < 0.34:
            recs.append(_rec("mention", "medium",
                f"Low organic discoverability ({unbranded:.0%}): the brand rarely surfaces "
                "for category questions where it isn't named. Improve topical authority for "
                "the category to be recommended without being asked by name."))
        elif unbranded >= 0.67:
            recs.append(_rec("mention", "low",
                f"Strong organic discoverability ({unbranded:.0%}) — the model recommends the "
                "brand unprompted for category queries. Monitor over time as models update."))

    # --- retrieval ---
    if retrieval:
        if not retrieval.get("available"):
            recs.append(_rec("retrieval", "low",
                f"Retrieval check was not available ({retrieval.get('reason', 'unknown')}). "
                "Configure EXA_API_KEY to measure whether the page is retrieved by "
                "search-grounded AI engines for category queries."))
        else:
            best_rank = retrieval.get("best_rank")
            competitors = retrieval.get("competitors", []) or []
            comp_names = ", ".join(c["domain"] for c in competitors[:4])

            if not retrieval.get("brand_url_retrieved"):
                msg = (
                    "The page was NOT retrieved by Exa for any category query — it is "
                    "effectively invisible to search-grounded AI answer engines for this "
                    "topic. Publish authoritative, keyword-aligned content for the category "
                    "and earn backlinks so search retrieval can surface it."
                )
                if comp_names:
                    msg += f" Competitors currently retrieved for these queries: {comp_names}."
                recs.append(_rec("retrieval", "high", msg))
            elif best_rank and best_rank > 3:
                msg = (
                    f"The page is retrieved but ranks low (best position {best_rank}). "
                    "Strengthen topical depth, internal linking, and citations to climb into "
                    "the top 3 where AI engines pull most sources."
                )
                if comp_names:
                    msg += f" Higher-ranked competitors: {comp_names}."
                recs.append(_rec("retrieval", "medium", msg))
            else:
                recs.append(_rec("retrieval", "low",
                    f"Strong retrieval visibility (best rank {best_rank}). The page is a "
                    "top source for its category — maintain content freshness and authority."))

    return recs


def score_audit(
    access: Optional[Dict[str, Any]],
    technical: Optional[Dict[str, Any]],
    mention: Optional[Dict[str, Any]],
    retrieval: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute all sub-scores, the composite, and recommendations."""
    access_score = _access_score(access.get("bot_rules", {})) if access else 0.0
    technical_score = float(technical.get("technical_score", 0.0)) if technical else 0.0
    mention_score = _mention_score(mention)
    retrieval_score = _retrieval_score(retrieval)

    composite = compute_composite(access_score, technical_score, mention_score, retrieval_score)

    # Composite knowledge gate: the headline number is "AI visibility". A brand
    # the model does not genuinely know cannot be highly visible no matter how
    # well-built the page is. Stricter caps: only genuinely known AND organically
    # discoverable brands are allowed into the high range.
    brand_known = (mention or {}).get("brand_known", "unknown")
    unbranded = float((mention or {}).get("unbranded_mention_rate", 0.0))
    if brand_known == "unknown":
        composite = round(min(composite, 30.0), 2)
    elif brand_known == "hallucinated":
        composite = round(min(composite, 40.0), 2)
    elif brand_known == "known" and unbranded < 0.34:
        # Known by name but not surfacing organically — capped out of the top tier.
        composite = round(min(composite, 65.0), 2)

    recommendations = generate_recommendations(access, technical, mention, retrieval)

    print(
        f"[scoring] composite={composite} brand_known={brand_known} "
        f"(access={access_score}, technical={technical_score}, "
        f"mention={mention_score}, retrieval={retrieval_score})"
    )

    return {
        "composite_score": composite,
        "sub_scores": {
            "access": access_score,
            "technical": technical_score,
            "mention": mention_score,
            "retrieval": retrieval_score,  # may be None
        },
        "recommendations": recommendations,
    }
