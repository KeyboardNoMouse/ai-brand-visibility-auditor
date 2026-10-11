"""Application configuration. Loads environment variables and fails fast if
required keys are missing."""

import os
import sys

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


# --- API keys -------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# Exa is optional per the spec (retrieval module degrades gracefully).
EXA_API_KEY = os.getenv("EXA_API_KEY", "").strip()

# --- Paths ----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DB_PATH = os.getenv("GEO_AUDITOR_DB", os.path.join(PROJECT_ROOT, "geo_auditor.db"))

# --- Model / tuning constants --------------------------------------------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
# Which LLM provider to use for AI-visibility testing. Provider-agnostic:
# add "openai"/"claude" implementations in ai_query_simulator.PROVIDERS.
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini")
RUNS_PER_PROMPT = int(os.getenv("RUNS_PER_PROMPT", "3"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "15"))
USER_AGENT = os.getenv(
    "GEO_AUDITOR_UA",
    "Mozilla/5.0 (compatible; GEOAuditorBot/1.0; +https://example.com/bot)",
)


def validate_startup_config() -> None:
    """Fail fast if hard-required configuration is missing.

    GEMINI_API_KEY is required — the AI mention module is core.
    EXA_API_KEY is optional; the retrieval module degrades gracefully, so we
    only warn about it.
    """
    if not GEMINI_API_KEY:
        raise ConfigError(
            "GEMINI_API_KEY is not set. Add it to your environment or .env file. "
            "The AI mention-testing module cannot run without it."
        )

    if not EXA_API_KEY:
        # Not fatal — retrieval_checker handles absence gracefully.
        print(
            "[config] WARNING: EXA_API_KEY is not set. The retrieval module "
            "will report 'not available' and be excluded from scoring.",
            file=sys.stderr,
        )


def exa_enabled() -> bool:
    return bool(EXA_API_KEY)
