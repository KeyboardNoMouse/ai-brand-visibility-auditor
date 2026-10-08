"""Module 5 — retrieval visibility via Exa.ai.

Runs several region-aware category queries against the Exa.ai search API and
checks whether the audited domain is retrieved, at what rank, and which
competitor domains outrank it. Search-grounded retrieval is what powers AI
answer engines (Perplexity, ChatGPT Search, etc.), so this measures whether the
page would actually be pulled in as a source.

This module is genuinely optional. Every call is wrapped so that a missing API
key or a failed request records a clear "not available" state rather than
crashing the audit.
"""

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from .. import config

EXA_SEARCH_ENDPOINT = "https://api.exa.ai/search"
NUM_RESULTS = 10
MAX_COMPETITORS = 6


def _domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def _build_queries(category: str, brand_name: str, region: Optional[str]) -> List[str]:
    """A small panel of natural category queries an AI answer engine might run."""
    base = category.strip() if category and category != "this product category" else brand_name
    region_suffix = f" in {region}" if region else ""
    return [
        f"best {base}{region_suffix}",
        f"top {base} companies{region_suffix}",
        f"recommended {base} providers{region_suffix}",
    ]


def _rank_and_competitors(results: list, target_url: str) -> Dict[str, Any]:
    """Find the target's rank and the competitor domains that outrank it."""
    target_domain = _domain(target_url)
    rank: Optional[int] = None
    competitors: List[Dict[str, Any]] = []
    for idx, item in enumerate(results, start=1):
        result_url = (item or {}).get("url", "")
        dom = _domain(result_url)
        if not dom:
            continue
        if dom == target_domain and rank is None:
            rank = idx
        elif rank is None and dom != target_domain:
            # a domain ranked above the target (or target not yet found)
            competitors.append({"domain": dom, "rank": idx, "title": (item or {}).get("title", "")})
    return {"rank": rank, "competitors": competitors[:MAX_COMPETITORS]}


async def _one_query(
    client: httpx.AsyncClient, query: str, target_url: str
) -> Dict[str, Any]:
    payload = {"query": query, "numResults": NUM_RESULTS, "type": "auto"}
    headers = {"x-api-key": config.EXA_API_KEY, "Content-Type": "application/json"}
    resp = await client.post(EXA_SEARCH_ENDPOINT, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", []) or []
    rc = _rank_and_competitors(results, target_url)
    return {
        "query": query,
        "rank": rc["rank"],
        "retrieved": rc["rank"] is not None,
        "competitors": rc["competitors"],
        "result_count": len(results),
    }


async def check_retrieval(
    url: str,
    category: str,
    brand_name: str,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """Query Exa.ai across several category queries and aggregate retrieval.

    Never raises. Always returns a dict with ``available`` so the scoring
    engine knows whether to include the signal.
    """
    queries = _build_queries(category, brand_name, region)
    primary_query = queries[0]

    if not config.exa_enabled():
        print("[retrieval] EXA_API_KEY missing — skipping (not available)")
        return {
            "available": False,
            "reason": "EXA_API_KEY not configured",
            "query_text": primary_query,
            "brand_url_retrieved": None,
            "retrieved_rank": None,
            "queries_run": 0,
            "best_rank": None,
            "retrieval_rate": None,
            "competitors": [],
            "per_query": [],
            "raw_response": {},
        }

    print(f"[retrieval] querying Exa.ai across {len(queries)} queries (region={region or 'global'})")
    try:
        async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT_SECONDS * 2) as client:
            per_query = await asyncio.gather(
                *[_one_query(client, q, url) for q in queries]
            )
    except httpx.HTTPError as exc:
        print(f"[retrieval] Exa call failed: {exc}")
        return {
            "available": False,
            "reason": f"Exa request failed: {exc}",
            "query_text": primary_query,
            "brand_url_retrieved": None,
            "retrieved_rank": None,
            "queries_run": 0,
            "best_rank": None,
            "retrieval_rate": None,
            "competitors": [],
            "per_query": [],
            "raw_response": {},
        }

    ranks = [q["rank"] for q in per_query if q["rank"] is not None]
    best_rank = min(ranks) if ranks else None
    retrieved_count = sum(1 for q in per_query if q["retrieved"])
    retrieval_rate = round(retrieved_count / len(per_query), 4) if per_query else 0.0

    # Aggregate competitor domains that outranked the brand (dedup, keep best rank).
    comp_map: Dict[str, Dict[str, Any]] = {}
    for q in per_query:
        for c in q["competitors"]:
            existing = comp_map.get(c["domain"])
            if not existing or c["rank"] < existing["rank"]:
                comp_map[c["domain"]] = c
    competitors = sorted(comp_map.values(), key=lambda c: c["rank"])[:MAX_COMPETITORS]

    print(
        f"[retrieval] best_rank={best_rank} retrieval_rate={retrieval_rate} "
        f"competitors={[c['domain'] for c in competitors]}"
    )

    return {
        "available": True,
        "reason": None,
        "query_text": primary_query,
        "brand_url_retrieved": best_rank is not None,
        "retrieved_rank": best_rank,
        "queries_run": len(per_query),
        "best_rank": best_rank,
        "retrieval_rate": retrieval_rate,
        "competitors": competitors,
        "per_query": per_query,
        "raw_response": {"per_query": per_query},
    }
