"""SQLite persistence layer.

Uses the stdlib ``sqlite3`` module (no ORM). All functions accept/return plain
dicts so they map cleanly onto the API's JSON responses.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from . import config

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Yield a connection with row factory set, WAL mode, and foreign keys enabled."""
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables from schema.sql if they don't already exist."""
    with open(SCHEMA_FILE, "r", encoding="utf-8") as fh:
        ddl = fh.read()
    with get_conn() as conn:
        conn.executescript(ddl)
    print(f"[db] initialized schema at {config.DB_PATH}")


# --- audits ---------------------------------------------------------------

def create_audit(audit_id: str, brand_name: str, url: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audits (id, brand_name, url, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (audit_id, brand_name, url, utcnow_iso()),
        )


def set_audit_status(audit_id: str, status: str, error_message: Optional[str] = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE audits SET status = ?, error_message = ? WHERE id = ?",
            (status, error_message, audit_id),
        )


def complete_audit(audit_id: str, composite_score: Optional[float]) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE audits SET status = 'completed', composite_score = ?, "
            "completed_at = ? WHERE id = ?",
            (composite_score, utcnow_iso(), audit_id),
        )


def get_audit_row(audit_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
        return dict(row) if row else None


def list_audits() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, brand_name, url, composite_score, status, created_at "
            "FROM audits ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# --- access_results -------------------------------------------------------

def save_access_results(audit_id: str, data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO access_results "
            "(audit_id, robots_txt_found, robots_txt_raw, llms_txt_found, "
            " llms_txt_raw, bot_rules_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                data.get("robots_txt_found"),
                data.get("robots_txt_raw"),
                data.get("llms_txt_found"),
                data.get("llms_txt_raw"),
                json.dumps(data.get("bot_rules", {})),
            ),
        )


def get_access_results(audit_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM access_results WHERE audit_id = ?", (audit_id,)
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["bot_rules"] = json.loads(out.pop("bot_rules_json") or "{}")
        return out


# --- technical_results ----------------------------------------------------

def save_technical_results(audit_id: str, data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO technical_results "
            "(audit_id, meta_description, has_schema_data, schema_types_json, "
            " h1_count, heading_structure_json, word_count, has_statistics, "
            " has_quotations, has_outbound_citations, technical_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                data.get("meta_description"),
                data.get("has_schema_data"),
                json.dumps(data.get("schema_types", [])),
                data.get("h1_count"),
                json.dumps(data.get("heading_structure", {})),
                data.get("word_count"),
                data.get("has_statistics"),
                data.get("has_quotations"),
                data.get("has_outbound_citations"),
                data.get("technical_score"),
            ),
        )


def get_technical_results(audit_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM technical_results WHERE audit_id = ?", (audit_id,)
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        out["schema_types"] = json.loads(out.pop("schema_types_json") or "[]")
        out["heading_structure"] = json.loads(out.pop("heading_structure_json") or "{}")
        return out


# --- ai_prompt_runs -------------------------------------------------------

def save_prompt_run(audit_id: str, run: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO ai_prompt_runs "
            "(id, audit_id, prompt_text, prompt_type, run_number, raw_response, "
            " brand_mentioned, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run["id"],
                audit_id,
                run["prompt_text"],
                run["prompt_type"],
                run["run_number"],
                run.get("raw_response"),
                run.get("brand_mentioned"),
                utcnow_iso(),
            ),
        )


def get_prompt_runs(audit_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_prompt_runs WHERE audit_id = ? "
            "ORDER BY prompt_type, prompt_text, run_number",
            (audit_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# --- retrieval_results ----------------------------------------------------

def save_retrieval_results(audit_id: str, data: Dict[str, Any]) -> None:
    # Persist the full enriched payload (competitors, per_query, best_rank,
    # retrieval_rate, available flag) in the JSON column so GET can reconstruct
    # the same object the pipeline produced, without a schema migration.
    full = {
        "available": data.get("available"),
        "reason": data.get("reason"),
        "best_rank": data.get("best_rank"),
        "retrieval_rate": data.get("retrieval_rate"),
        "queries_run": data.get("queries_run"),
        "competitors": data.get("competitors", []),
        "per_query": data.get("per_query", []),
    }
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO retrieval_results "
            "(audit_id, query_text, brand_url_retrieved, retrieved_rank, "
            " raw_response_json) VALUES (?, ?, ?, ?, ?)",
            (
                audit_id,
                data.get("query_text"),
                data.get("brand_url_retrieved"),
                data.get("retrieved_rank"),
                json.dumps(full),
            ),
        )


def get_retrieval_results(audit_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM retrieval_results WHERE audit_id = ?", (audit_id,)
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        full = json.loads(out.pop("raw_response_json") or "{}")
        # Merge the enriched fields back onto the flat row.
        out.update({
            "available": full.get("available", False),
            "reason": full.get("reason"),
            "best_rank": full.get("best_rank"),
            "retrieval_rate": full.get("retrieval_rate"),
            "queries_run": full.get("queries_run"),
            "competitors": full.get("competitors", []),
            "per_query": full.get("per_query", []),
        })
        return out


# --- mention_summary ------------------------------------------------------

def save_mention_summary(audit_id: str, data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO mention_summary "
            "(audit_id, category, brand_known, knowledge_consistency, "
            " explicit_unknown_rate, branded_mention_rate, unbranded_mention_rate, "
            " composite_visibility_rate) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                data.get("category"),
                data.get("brand_known"),
                data.get("knowledge_consistency"),
                data.get("explicit_unknown_rate"),
                data.get("branded_mention_rate"),
                data.get("unbranded_mention_rate"),
                data.get("composite_visibility_rate"),
            ),
        )


def get_mention_summary(audit_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM mention_summary WHERE audit_id = ?", (audit_id,)
        ).fetchone()
        return dict(row) if row else None


# --- recommendations ------------------------------------------------------
def save_recommendations(audit_id: str, recs: List[Dict[str, Any]]) -> None:
    with get_conn() as conn:
        for rec in recs:
            conn.execute(
                "INSERT INTO recommendations (id, audit_id, category, severity, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (rec["id"], audit_id, rec["category"], rec["severity"], rec["description"]),
            )


def get_recommendations(audit_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE audit_id = ? "
            "ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END",
            (audit_id,),
        ).fetchall()
        return [dict(r) for r in rows]
