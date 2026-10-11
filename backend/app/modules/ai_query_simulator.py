"""Module 4 — AI visibility & knowledge testing.

This module measures how *genuinely visible* a brand is to an AI model, rather
than whether a brand string trivially appears in a response. It does three
things:

1. **Category inference** — derives the brand's real product category from page
   content via one grounding call, WITHOUT ever leaking the brand name into the
   category (so unbranded prompts stay truly unbranded).

2. **Knowledge grounding + hallucination detection** — asks the model factual
   questions about the brand several times and measures whether the answers are
   *consistent*. A model that invents a different story each time (e.g. "it's
   malware" / "it's a YouTuber" / "it's an APT group") does NOT actually know
   the brand — that is hallucination, not visibility. Output:
   ``brand_known`` ∈ {"known", "hallucinated", "unknown"}.

3. **Organic discoverability** — runs unbranded category prompts and checks
   whether the model recommends the brand on its own. This is the strongest
   signal of real AI visibility.

Provider-agnostic: all model calls go through a ``LLMProvider`` protocol. Only
Gemini is wired in by default (matching the project's single-provider scope),
but adding Claude or OpenAI is a matter of implementing one method — see
``PROVIDERS`` and the README.
"""

import asyncio
import json
import re
import uuid
from typing import Any, Dict, List, Optional, Protocol

import httpx

from .. import config

# --- provider abstraction -------------------------------------------------

class LLMProvider(Protocol):
    name: str

    async def generate(self, client: httpx.AsyncClient, prompt: str) -> str:
        """Return the model's text response for a single prompt."""
        ...


class GeminiProvider:
    """Google Gemini via the REST generateContent endpoint."""

    name = "gemini"
    _ENDPOINT = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "{model}:generateContent"
    )
    RETRYABLE_STATUS = {429, 503}
    MAX_RETRIES = 3

    async def generate(self, client: httpx.AsyncClient, prompt: str) -> str:
        url = self._ENDPOINT.format(model=config.GEMINI_MODEL)
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await client.post(
                    url,
                    params={"key": config.GEMINI_API_KEY},
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code in self.RETRYABLE_STATUS and attempt < self.MAX_RETRIES - 1:
                    backoff = 2 ** attempt
                    print(f"[ai] transient {resp.status_code}, retrying in {backoff}s")
                    await asyncio.sleep(backoff)
                    continue
                resp.raise_for_status()
                data = resp.json()
                try:
                    parts = data["candidates"][0]["content"]["parts"]
                    return "".join(p.get("text", "") for p in parts).strip()
                except (KeyError, IndexError, TypeError) as e:
                    print(f"[ai] unexpected response structure: {data}")
                    return ""
            except httpx.HTTPStatusError as e:
                print(f"[ai] HTTP error {e.response.status_code}: {e.response.text[:200]}")
                if e.response.status_code == 404:
                    print(f"[ai] Model '{config.GEMINI_MODEL}' not found. Check GEMINI_MODEL in config.")
                raise
            except httpx.HTTPError as e:
                print(f"[ai] Network error: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    backoff = 2 ** attempt
                    print(f"[ai] retrying in {backoff}s")
                    await asyncio.sleep(backoff)
                    continue
                raise
        # All retries exhausted on retryable status codes.
        return ""


# To add Claude or OpenAI: implement a class with the same `generate` signature
# (name + async generate(client, prompt) -> str) and register it here. The rest
# of the pipeline and scoring are provider-agnostic.
#
#   class OpenAIProvider:      name = "openai"      async def generate(...)
#   class ClaudeProvider:      name = "claude"      async def generate(...)
#
PROVIDERS: Dict[str, LLMProvider] = {"gemini": GeminiProvider()}


def get_provider() -> LLMProvider:
    return PROVIDERS[config.AI_PROVIDER]


# --- tuning constants -----------------------------------------------------

MAX_CONCURRENT_CALLS = 3
KNOWLEDGE_PROBES = 3          # repeats of the factual question for consistency
CONSISTENCY_KNOWN = 0.45     # >= this Jaccard similarity => consistent knowledge
CONSISTENCY_UNKNOWN = 0.2    # <= this AND no discovery => not genuinely known
# Below this, a brand the model *claims* to know is telling genuinely different
# stories each time (e.g. malware / YouTuber / APT group) => hallucination.
# NOTE: This threshold must account for paraphrase variation — well-known brands
# can produce semantically consistent but lexically diverse fact sentences (e.g.
# "Stripe is a payment processing company" vs "Stripe provides online payment
# infrastructure") with Jaccard as low as ~0.18. Set above the paraphrase
# floor to avoid false positives.
CONSISTENCY_HALLUCINATED = 0.30

# Unbranded discoverability prompts (the real visibility signal). {category}
# is filled with the inferred category. The brand name never appears here.
UNBRANDED_PROMPTS: List[str] = [
    "List the top companies or products for {category}. "
    "Answer with a plain comma-separated list of names only, no descriptions.",
    "Recommend the best providers for {category}. "
    "Answer with a plain comma-separated list of names only, no descriptions.",
    "Which brands are considered leaders in {category}? "
    "Answer with a plain comma-separated list of names only, no descriptions.",
]

# Phrases that signal the model does NOT actually know the brand.
_UNKNOWN_MARKERS = re.compile(
    r"\b(i (?:do not|don't) have (?:any )?(?:specific |reliable )?information|"
    r"i'm not (?:familiar|aware)|not familiar with|no (?:widely |publicly )?"
    r"(?:available|known) information|cannot find|couldn't find|"
    r"there is no (?:widely )?(?:known|recognized|public)|"
    r"may be a (?:private|small|niche|local)|does not appear to be a "
    r"(?:well-known|widely recognized)|unable to find|i am not certain|"
    r"it'?s possible (?:you|that)|could refer to (?:a few|several|multiple))",
    re.IGNORECASE,
)


def _tokens(text: str) -> set:
    """Content tokens (lowercased words >=4 chars, minus common filler)."""
    words = re.findall(r"[a-z0-9]{4,}", (text or "").lower())
    stop = {
        "that", "this", "with", "from", "have", "your", "about", "which",
        "there", "their", "would", "could", "based", "known", "these", "some",
        "most", "here", "what", "when", "they", "them", "also", "very", "into",
        "such", "than", "then", "been", "being", "will", "more", "like",
    }
    return {w for w in words if w not in stop}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --- category inference (no brand leak) -----------------------------------

_GENERIC_STOP = re.compile(
    r"\b(home|homepage|official site|welcome|the official|shop|store online|"
    r"buy online|login|sign in)\b",
    re.IGNORECASE,
)


async def infer_category(
    provider: LLMProvider,
    client: httpx.AsyncClient,
    brand_name: str,
    scraped: Optional[Dict[str, Any]],
) -> str:
    """Infer the brand's product/service category from page content via the
    model. Falls back to metadata heuristics. The brand name is explicitly
    excluded from the result so unbranded prompts remain unbranded."""
    meta = (scraped or {}).get("meta_description") or ""
    title = (scraped or {}).get("title") or ""
    headings = (scraped or {}).get("headings", {}) or {}
    h1 = " ".join(headings.get("h1", [])[:2])
    context = f"Title: {title}\nDescription: {meta}\nHeadings: {h1}".strip()
    word_count = int((scraped or {}).get("word_count", 0) or 0)

    # Detect thin / bot-wall / error pages. If the page has almost no real
    # content or looks like an access-denied/error shell, its text is useless
    # for category inference — infer from the brand name instead so a known
    # brand with an unscrapeable homepage isn't mis-categorized.
    combined = f"{title} {meta} {h1}".lower()
    error_markers = (
        "access denied", "403 forbidden", "404 not found", "error",
        "are you a robot", "captcha", "enable javascript", "just a moment",
        "attention required", "page not found", "bot detection",
    )
    thin_or_error = word_count < 40 or any(m in combined for m in error_markers)

    if not thin_or_error:
        prompt = (
            "You are categorizing a company by its product/service market. "
            "Given the page details below, respond with ONLY a short generic "
            "category phrase (2-5 words, e.g. 'running shoes and apparel', "
            "'payment processing APIs', 'project management software'). "
            "Do NOT include the company's own name. Do NOT add punctuation or "
            "explanation.\n\n"
            f"{context}"
        )
        try:
            raw = await provider.generate(client, prompt)
        except httpx.HTTPError:
            raw = ""
        category = _clean_category(raw, brand_name)
        if category:
            return category

        # metadata heuristic (still stripping brand)
        for source in (meta, title):
            cleaned = _clean_category(re.sub(r"[|\-–—:].*$", "", source), brand_name)
            if cleaned:
                return cleaned

    # Thin/error page (or content inference failed): infer from the brand name.
    brand_prompt = (
        f"What product or service category is the brand/company \"{brand_name}\" "
        f"best known for? Respond with ONLY a short generic category phrase "
        f"(2-5 words, e.g. 'e-commerce marketplace', 'athletic footwear'). "
        f"Do NOT include the brand's own name. If you don't know the brand, "
        f"respond with exactly 'unknown'."
    )
    try:
        raw2 = await provider.generate(client, brand_prompt)
    except httpx.HTTPError:
        raw2 = ""
    cat2 = _clean_category(raw2, brand_name)
    if cat2 and cat2.lower() != "unknown":
        return cat2

    return "this product category"


def _clean_category(raw: str, brand_name: str) -> str:
    if not raw:
        return ""
    cat = raw.strip().strip('".').splitlines()[0].strip()
    # Remove the brand name if the model leaked it in.
    cat = re.sub(re.escape(brand_name), "", cat, flags=re.IGNORECASE).strip()
    cat = _GENERIC_STOP.sub("", cat).strip(" -–—,")
    if 3 <= len(cat) <= 60 and cat.lower() not in {brand_name.lower(), ""}:
        return cat
    return ""


# --- region derivation ----------------------------------------------------

# Map common ccTLDs to a human region phrase used to contextualize prompts so
# regional brands (e.g. Indian marketplaces) can be discovered organically.
_TLD_REGION = {
    "in": "India", "co.in": "India",
    "uk": "the United Kingdom", "co.uk": "the United Kingdom",
    "au": "Australia", "com.au": "Australia",
    "ca": "Canada", "de": "Germany", "fr": "France", "jp": "Japan",
    "br": "Brazil", "com.br": "Brazil", "sg": "Singapore", "ae": "the UAE",
    "id": "Indonesia", "co.id": "Indonesia", "za": "South Africa",
    "ng": "Nigeria", "mx": "Mexico", "es": "Spain", "it": "Italy",
    "nl": "the Netherlands", "ru": "Russia", "cn": "China",
}


def _derive_region(url: str, scraped: Optional[Dict[str, Any]]) -> Optional[str]:
    """Best-effort region from the URL's ccTLD (e.g. .in -> India)."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().split(":")[0]
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TLD_REGION:
        return _TLD_REGION[".".join(parts[-2:])]
    if parts and parts[-1] in _TLD_REGION:
        return _TLD_REGION[parts[-1]]
    return None


# --- knowledge grounding + hallucination detection ------------------------

# Structured verdict line the model must emit, e.g. "VERDICT: known".
_VERDICT_RE = re.compile(r"verdict\s*[:\-]\s*(known|unsure|unknown)", re.IGNORECASE)


async def probe_knowledge(
    provider: LLMProvider,
    client: httpx.AsyncClient,
    brand_name: str,
    region: Optional[str],
    semaphore: asyncio.Semaphore,
) -> Dict[str, Any]:
    """Ask the model to explicitly self-assess whether it knows the brand, and
    separately capture a factual claim to cross-check for hallucination.

    The explicit self-assessment is the primary signal (far more reliable than
    token-overlap). Consistency of the stated facts is a secondary
    hallucination guard: a model that "claims" to know but tells a different
    story each time is hallucinating.
    """
    region_hint = f" It is a company/brand based in or operating in {region}." if region else ""
    verdict_prompt = (
        f"Do you have reliable, factual knowledge about the specific real-world "
        f"brand/company named \"{brand_name}\"?{region_hint}\n"
        f"Answer in exactly this format on three lines:\n"
        f"VERDICT: <known|unsure|unknown>\n"
        f"FACT: <one specific verifiable fact about it, or 'none' if you don't know>\n"
        f"HOME_MARKET: <the primary country/region it operates in, or 'unknown'>\n"
        f"Use 'known' ONLY if you are confident about what this brand actually is. "
        f"Use 'unknown' if you have no reliable information. Use 'unsure' if you "
        f"are guessing."
    )

    async def one_probe(n: int) -> Dict[str, Any]:
        async with semaphore:
            try:
                text = await provider.generate(client, verdict_prompt)
            except httpx.HTTPError as exc:
                text = f"[error: {exc}]"
        return {
            "id": str(uuid.uuid4()),
            "prompt_type": "knowledge",
            "prompt_text": verdict_prompt,
            "run_number": n,
            "raw_response": text,
            "brand_mentioned": None,
        }

    probes = await asyncio.gather(*[one_probe(n) for n in range(1, KNOWLEDGE_PROBES + 1)])
    texts = [p["raw_response"] for p in probes if not p["raw_response"].startswith("[error")]

    if not texts:
        return {
            "verdict_known_rate": 0.0, "verdict_unknown_rate": 1.0,
            "consistency": 0.0, "explicit_unknown_rate": 1.0,
            "detected_region": None, "probes": probes,
        }

    # Parse the explicit VERDICT lines.
    verdicts: List[str] = []
    facts: List[str] = []
    home_markets: List[str] = []
    for t in texts:
        m = _VERDICT_RE.search(t)
        verdicts.append(m.group(1).lower() if m else "unsure")
        fm = re.search(r"fact\s*[:\-]\s*(.+)", t, re.IGNORECASE)
        facts.append(fm.group(1).strip() if fm else t)
        hm = re.search(r"home_market\s*[:\-]\s*(.+)", t, re.IGNORECASE)
        if hm:
            home_markets.append(hm.group(1).strip().rstrip(".").strip())

    # Pick the most common non-'unknown' home market as a region hint.
    detected_region: Optional[str] = None
    cleaned_markets = [
        h for h in home_markets
        if h and h.lower() not in {"unknown", "none", "n/a", "global", "worldwide"}
    ]
    if cleaned_markets:
        from collections import Counter
        detected_region = Counter(cleaned_markets).most_common(1)[0][0]

    n = len(verdicts)
    verdict_known_rate = verdicts.count("known") / n
    verdict_unknown_rate = verdicts.count("unknown") / n

    # Explicit "I don't know" marker rate (belt-and-suspenders with verdicts).
    explicit_unknown = sum(1 for t in texts if _UNKNOWN_MARKERS.search(t))
    explicit_unknown_rate = max(verdict_unknown_rate, explicit_unknown / n)

    # Fact consistency: do the stated facts overlap? (hallucination guard)
    token_sets = [_tokens(f) for f in facts]
    sims: List[float] = []
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            sims.append(_jaccard(token_sets[i], token_sets[j]))
    consistency = round(sum(sims) / len(sims), 4) if sims else 1.0

    print(
        f"[ai] knowledge: verdict_known={round(verdict_known_rate,2)} "
        f"verdict_unknown={round(verdict_unknown_rate,2)} "
        f"fact_consistency={consistency}"
    )
    return {
        "verdict_known_rate": round(verdict_known_rate, 4),
        "verdict_unknown_rate": round(verdict_unknown_rate, 4),
        "consistency": consistency,
        "explicit_unknown_rate": round(explicit_unknown_rate, 4),
        "detected_region": detected_region,
        "probes": probes,
    }


def _decide_brand_known(
    verdict_known_rate: float,
    verdict_unknown_rate: float,
    consistency: float,
    explicit_unknown_rate: float,
    unbranded_rate: float,
) -> str:
    """Combine the model's explicit self-assessment, hallucination cross-check,
    and organic discovery into a final verdict.

    Priority:
      1. Strong organic discovery => known (hard proof).
      2. Model explicitly says unknown most of the time => unknown.
      3. Model confidently and repeatedly says 'known' => known. The explicit
         self-assessment is trusted here; short factual sentences vary in
         wording so token-overlap consistency is only used to catch genuine
         divergence (rule 4), not to override a unanimous confident verdict.
      4. Model claims knowledge but facts genuinely diverge (very low
         consistency) => hallucinated.
      5. Otherwise unknown.
    """
    # 1. Recommended unprompted for category queries — demonstrably known.
    if unbranded_rate >= 0.34:
        return "known"
    # 2. Explicitly disclaims knowledge.
    if verdict_unknown_rate >= 0.5 or explicit_unknown_rate >= 0.6:
        return "unknown"
    # 3. Confident self-assessment. A high 'known' rate is trusted unless the
    #    facts are wildly contradictory (handled next).
    if verdict_known_rate >= 0.6 and consistency >= CONSISTENCY_HALLUCINATED:
        return "known"
    # 4. Claims knowledge but facts genuinely diverge => hallucination.
    if verdict_known_rate >= 0.34 and consistency < CONSISTENCY_HALLUCINATED:
        return "hallucinated"
    # 5. Some 'known' signal with decent consistency but not strong enough.
    if verdict_known_rate >= 0.34 and consistency >= CONSISTENCY_KNOWN:
        return "known"
    # 6. Weak/mixed signals.
    return "unknown"


# --- organic discoverability (the real visibility signal) -----------------

def _brand_recommended(response_text: str, brand_name: str) -> bool:
    """Whether the brand appears as a recommended name in an unbranded answer.

    The prompt asks for a plain list of names, so a genuine match means the
    model surfaced the brand on its own."""
    if not response_text:
        return False
    hay = re.sub(r"[^a-z0-9]+", " ", response_text.lower())
    brand = re.sub(r"[^a-z0-9]+", " ", brand_name.lower()).strip()
    if not brand:
        return False
    # Regex word-boundary match on the normalized strings — handles brand
    # at the start/end of the response where the space-padding approach fails.
    return bool(re.search(r'(?<![a-z0-9])' + re.escape(brand) + r'(?![a-z0-9])', hay))


async def run_panel(
    brand_name: str,
    scraped: Optional[Dict[str, Any]] = None,
    url: str = "",
) -> Dict[str, Any]:
    """Run category inference, knowledge grounding, and organic discovery.

    Returns a dict with:
      - category, brand_known, knowledge_consistency
      - branded_knowledge_rate  (share of knowledge probes that were confident+consistent-ish)
      - unbranded_mention_rate  (organic discovery — the primary visibility metric)
      - per_prompt / runs        (evidence for storage + UI)
    Degrades gracefully on individual call failures.
    """
    provider = get_provider()
    timeout = httpx.Timeout(config.HTTP_TIMEOUT_SECONDS * 3)
    tld_region = _derive_region(url, scraped)

    async with httpx.AsyncClient(timeout=timeout) as client:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)

        category = await infer_category(provider, client, brand_name, scraped)

        # 1. knowledge grounding — explicit model self-assessment + hallucination
        # guard. Also detects the brand's home market for region context.
        knowledge = await probe_knowledge(provider, client, brand_name, tld_region, semaphore)

        # Region for discovery: prefer the model-detected home market, fall back
        # to the URL ccTLD. This lets regional brands on .com domains (e.g.
        # Indian companies) surface organically within their market.
        region = knowledge.get("detected_region") or tld_region
        geo_category = f"{category} in {region}" if region else category
        print(
            f"[ai] running visibility panel for '{brand_name}' "
            f"(category='{category}', region='{region or 'global'}')"
        )

        # 2. organic discovery (unbranded, region-contextualized)
        unbranded_prompts = [p.format(category=geo_category) for p in UNBRANDED_PROMPTS]

        async def discovery_run(prompt_text: str, n: int) -> Dict[str, Any]:
            async with semaphore:
                try:
                    text = await provider.generate(client, prompt_text)
                    recommended = _brand_recommended(text, brand_name)
                except httpx.HTTPError as exc:
                    text = f"[error: {exc}]"
                    recommended = False
            return {
                "id": str(uuid.uuid4()),
                "prompt_type": "unbranded",
                "prompt_text": prompt_text,
                "run_number": n,
                "raw_response": text,
                "brand_mentioned": recommended,
            }

        discovery_tasks = [
            discovery_run(p, n)
            for p in unbranded_prompts
            for n in range(1, config.RUNS_PER_PROMPT + 1)
        ]
        discovery_runs = await asyncio.gather(*discovery_tasks)

    # --- aggregate ---
    all_runs = list(knowledge["probes"]) + list(discovery_runs)

    unbranded_total = len(discovery_runs)
    unbranded_hits = sum(1 for r in discovery_runs if r["brand_mentioned"])
    unbranded_rate = round(unbranded_hits / unbranded_total, 4) if unbranded_total else 0.0

    # Final verdict: model's explicit self-assessment + hallucination guard +
    # organic discovery.
    brand_known = _decide_brand_known(
        knowledge["verdict_known_rate"],
        knowledge["verdict_unknown_rate"],
        knowledge["consistency"],
        knowledge["explicit_unknown_rate"],
        unbranded_rate,
    )
    branded_knowledge_rate = {
        "known": 1.0, "hallucinated": 0.15, "unknown": 0.0,
    }[brand_known]

    # per-prompt aggregates for the UI
    per_prompt: Dict[str, Dict[str, Any]] = {}
    for run in discovery_runs:
        key = run["prompt_text"]
        agg = per_prompt.setdefault(key, {
            "prompt_text": key, "prompt_type": "unbranded", "runs": 0, "mentions": 0,
        })
        agg["runs"] += 1
        if run["brand_mentioned"]:
            agg["mentions"] += 1
    for agg in per_prompt.values():
        agg["mention_rate"] = round(agg["mentions"] / agg["runs"], 4) if agg["runs"] else 0.0

    # knowledge probes shown as a pseudo-prompt group in the UI
    known_group = {
        "prompt_text": f"[Knowledge probe] What is {brand_name}?",
        "prompt_type": "knowledge",
        "runs": len(knowledge["probes"]),
        "mentions": 0,
        "mention_rate": branded_knowledge_rate,
    }
    per_prompt_list = [known_group] + list(per_prompt.values())

    print(
        f"[ai] brand_known={brand_known} branded_knowledge_rate={branded_knowledge_rate} "
        f"unbranded_rate={unbranded_rate}"
    )

    return {
        "category": category,
        "region": region,
        "brand_known": brand_known,
        "knowledge_consistency": knowledge["consistency"],
        "explicit_unknown_rate": knowledge["explicit_unknown_rate"],
        "branded_mention_rate": branded_knowledge_rate,
        "unbranded_mention_rate": unbranded_rate,
        "overall_mention_rate": round((branded_knowledge_rate + unbranded_rate) / 2, 4),  # deprecated alias
        "composite_visibility_rate": round((branded_knowledge_rate + unbranded_rate) / 2, 4),
        "runs": all_runs,
        "per_prompt": per_prompt_list,
    }
