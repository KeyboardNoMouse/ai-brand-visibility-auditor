"""FastAPI application — API orchestrator.

Exposes three endpoints and runs the full 6-module audit pipeline synchronously
(inline within the request), using asyncio.gather to parallelize independent
external calls.
"""

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config, database
from .modules import (
    access_checker,
    ai_query_simulator,
    content_analyzer,
    retrieval_checker,
    scraper,
)

app = FastAPI(title="AI Brand Visibility & GEO Auditor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # single-user local tool
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    config.validate_startup_config()  # fail fast if GEMINI key missing
    database.init_db()


# --- request/response models ---------------------------------------------

class AuditRequest(BaseModel):
    brand_name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)


class AuditListItem(BaseModel):
    id: str
    brand_name: str
    url: str
    composite_score: Optional[float]
    status: str
    created_at: str


# --- orchestration --------------------------------------------------------

async def run_pipeline(audit_id: str, brand_name: str, url: str) -> Dict[str, Any]:
    """Run all six modules and persist every table. Degrades gracefully:
    a failure in one module is recorded but does not abort the whole audit,
    except a hard scrape failure which fails the audit (nothing to analyze)."""
    database.set_audit_status(audit_id, "running")

    # Stage 1+2: scrape and access-check run concurrently (both hit the site).
    scrape_task = asyncio.create_task(scraper.scrape(url))
    access_task = asyncio.create_task(access_checker.check_access(url))

    scraped: Optional[Dict[str, Any]] = None
    scrape_error: Optional[str] = None
    try:
        scraped = await scrape_task
    except scraper.ScrapeError as exc:
        scrape_error = str(exc)
        print(f"[pipeline] scrape failed: {exc}")

    try:
        access = await access_task
    except Exception as exc:  # access_checker shouldn't raise, but be safe
        print(f"[pipeline] access check failed unexpectedly: {exc}")
        access = {
            "robots_txt_found": False, "robots_txt_raw": None,
            "llms_txt_found": False, "llms_txt_raw": None, "bot_rules": {},
        }

    database.save_access_results(audit_id, access)

    # If scrape failed there's nothing to analyze technically — fail the audit
    # but still persist the access results we did gather.
    if scraped is None:
        database.set_audit_status(audit_id, "failed", scrape_error)
        raise HTTPException(status_code=400, detail=scrape_error or "Could not fetch the page.")

    # Stage 3: technical analysis (pure CPU, from scraped data).
    technical = content_analyzer.analyze(scraped)
    database.save_technical_results(audit_id, technical)

    # Stage 4: AI visibility panel (category inference + knowledge grounding +
    # organic discovery). Run this first because it derives the real category.
    try:
        mention = await ai_query_simulator.run_panel(brand_name, scraped, url)
    except Exception as exc:
        print(f"[pipeline] mention panel failed: {exc}")
        mention = {
            "category": "this product category", "runs": [], "per_prompt": [],
            "brand_known": "unknown", "knowledge_consistency": 0.0,
            "explicit_unknown_rate": 1.0, "overall_mention_rate": 0.0,
            "branded_mention_rate": 0.0, "unbranded_mention_rate": 0.0,
        }
    # persist every individual prompt run + the derived summary
    for run in mention.get("runs", []):
        database.save_prompt_run(audit_id, run)
    database.save_mention_summary(audit_id, mention)

    # Stage 5: Exa retrieval, using the category + region the panel inferred.
    try:
        retrieval = await retrieval_checker.check_retrieval(
            url,
            mention.get("category", ""),
            brand_name,
            region=mention.get("region"),
        )
    except Exception as exc:  # retrieval_checker shouldn't raise, but be safe
        print(f"[pipeline] retrieval failed: {exc}")
        retrieval = {
            "available": False, "reason": str(exc), "query_text": None,
            "brand_url_retrieved": None, "retrieved_rank": None,
            "best_rank": None, "retrieval_rate": None, "competitors": [],
            "per_query": [], "queries_run": 0, "raw_response": {},
        }
    database.save_retrieval_results(audit_id, retrieval)

    # Stage 6: scoring + recommendations.
    from .modules import scoring_engine
    scored = scoring_engine.score_audit(access, technical, mention, retrieval)

    database.save_recommendations(audit_id, scored["recommendations"])
    database.complete_audit(audit_id, scored["composite_score"])

    return build_full_result(audit_id)


def build_full_result(audit_id: str) -> Dict[str, Any]:
    """Assemble the full joined result object for an audit."""
    audit = database.get_audit_row(audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")

    access = database.get_access_results(audit_id)
    technical = database.get_technical_results(audit_id)
    retrieval = database.get_retrieval_results(audit_id)
    prompt_runs = database.get_prompt_runs(audit_id)
    recommendations = database.get_recommendations(audit_id)
    summary = database.get_mention_summary(audit_id) or {}

    # Recompute sub-scores for display (cheap, deterministic).
    from .modules import scoring_engine
    mention_agg = _aggregate_prompt_runs(prompt_runs)
    # Merge the persisted knowledge-grounding summary (brand_known, etc.) with
    # the per-prompt evidence rebuilt from stored runs.
    mention_agg.update({
        "category": summary.get("category"),
        "brand_known": summary.get("brand_known", "unknown"),
        "knowledge_consistency": summary.get("knowledge_consistency", 0.0),
        "explicit_unknown_rate": summary.get("explicit_unknown_rate", 0.0),
        "branded_mention_rate": summary.get("branded_mention_rate", 0.0),
        "unbranded_mention_rate": summary.get("unbranded_mention_rate", 0.0),
        "overall_mention_rate": summary.get("overall_mention_rate", 0.0),
    })
    sub_scores = {
        "access": scoring_engine._access_score(access.get("bot_rules", {})) if access else 0.0,
        "technical": technical.get("technical_score") if technical else 0.0,
        "mention": scoring_engine._mention_score(mention_agg),
        "retrieval": scoring_engine._retrieval_score(retrieval),
    }

    return {
        "audit": audit,
        "sub_scores": sub_scores,
        "access": access,
        "technical": technical,
        "mention": mention_agg,
        "retrieval": retrieval,
        "recommendations": recommendations,
    }


def _aggregate_prompt_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rebuild mention aggregates from stored prompt runs for display."""
    per_prompt: Dict[str, Dict[str, Any]] = {}
    for r in runs:
        key = r["prompt_text"]
        agg = per_prompt.setdefault(key, {
            "prompt_text": key, "prompt_type": r["prompt_type"],
            "runs_detail": [], "runs": 0, "mentions": 0,
        })
        agg["runs"] += 1
        if r["brand_mentioned"]:
            agg["mentions"] += 1
        agg["runs_detail"].append({
            "run_number": r["run_number"],
            "brand_mentioned": bool(r["brand_mentioned"]),
            "raw_response": r["raw_response"],
        })
    for agg in per_prompt.values():
        agg["mention_rate"] = round(agg["mentions"] / agg["runs"], 4) if agg["runs"] else 0.0

    total = len(runs)
    total_mentions = sum(1 for r in runs if r["brand_mentioned"])
    branded = [r for r in runs if r["prompt_type"] == "branded"]
    unbranded = [r for r in runs if r["prompt_type"] == "unbranded"]

    def rate(subset: List[Dict[str, Any]]) -> float:
        return round(sum(1 for r in subset if r["brand_mentioned"]) / len(subset), 4) if subset else 0.0

    return {
        "per_prompt": list(per_prompt.values()),
        "overall_mention_rate": round(total_mentions / total, 4) if total else 0.0,
        "branded_mention_rate": rate(branded),
        "unbranded_mention_rate": rate(unbranded),
    }


# --- endpoints ------------------------------------------------------------

@app.post("/audits")
async def create_audit(req: AuditRequest) -> Dict[str, Any]:
    audit_id = str(uuid.uuid4())
    database.create_audit(audit_id, req.brand_name.strip(), req.url.strip())
    print(f"[api] starting audit {audit_id} for '{req.brand_name}' @ {req.url}")
    result = await run_pipeline(audit_id, req.brand_name.strip(), req.url.strip())
    return result


@app.get("/audits/{audit_id}")
def get_audit(audit_id: str) -> Dict[str, Any]:
    return build_full_result(audit_id)


@app.get("/audits")
def list_audits() -> List[AuditListItem]:
    return [AuditListItem(**row) for row in database.list_audits()]


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "exa_enabled": config.exa_enabled()}
