# AI Brand Visibility & GEO Auditor

Given a brand name and a URL, this tool audits how visible and machine-readable
the page is for AI systems and returns a composite 0–100 score with concrete,
traceable recommendations. It combines four signals:

1. **Crawler access** — can AI crawlers reach the page (robots.txt / llms.txt)?
2. **Technical readiness** — is the page structured for machine parsing
   (metadata, schema.org, headings, content signals)?
3. **AI mention rate** — does the brand get mentioned when a fixed panel of
   prompts is run against Gemini (branded + unbranded, each repeated)?
4. **Retrieval visibility** — is the page retrieved for relevant queries via
   the Exa.ai search API?

## Architecture

```
Client dashboard (Next.js + Tailwind)
        │
        ▼
API orchestrator (FastAPI)  ── runs the pipeline synchronously, inline
        │
        ├── Web scraper        (HTTPX + BeautifulSoup)
        ├── Access checker     (robots.txt / llms.txt bot rules)
        ├── Content analyzer   (schema & content signals)
        ├── AI query simulator ── Gemini API   (branded + unbranded, repeated)
        └── Retrieval checker  ── Exa.ai API   (search-grounded retrieval)
        │
        ▼
Scoring & recommendation engine → SQLite (audits, scores, evidence, history)
```

The pipeline runs entirely within the request. A single audit takes ~15–30
seconds. There is no job queue, no background worker, no auth, and no
multi-tenancy — it is a single-user local tool.

## Repository layout

```
backend/
  app/
    config.py                  # env loading + fail-fast validation
    database.py                # sqlite3 persistence layer
    schema.sql                 # table definitions
    main.py                    # FastAPI app + pipeline orchestration
    modules/
      scraper.py               # 1. page fetch + parse
      access_checker.py        # 2. robots.txt / llms.txt bot rules
      content_analyzer.py      # 3. technical + content scoring
      ai_query_simulator.py    # 4. Gemini mention testing
      retrieval_checker.py     # 5. Exa.ai retrieval (optional)
      scoring_engine.py        # 6. composite score + recommendations
  requirements.txt
  .env.example
frontend/
  app/                         # Next.js App Router single-page UI
  package.json
  .env.example
```

## Prerequisites

- Python 3.10+
- Node.js 18+
- A **Gemini API key** (required) - Get one at https://ai.google.dev/
  - Note: The current model used is `gemini-3.8-flash` (as of October 2024)
  - Older models like `gemini-2.0-flash` are no longer available
- An **Exa.ai API key** (optional — retrieval degrades gracefully without it)

## Environment variables

Backend (`backend/.env`):

```
GEMINI_API_KEY=your_gemini_key_here      # required
EXA_API_KEY=your_exa_key_here            # optional
```

If `GEMINI_API_KEY` is missing the backend **fails fast at startup** with a
clear message. If `EXA_API_KEY` is missing it only warns, and the retrieval
signal is reported as "not available" and excluded from scoring.

Frontend (`frontend/.env.local`, optional):

```
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

## Run the backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env            # then fill in GEMINI_API_KEY
uvicorn app.main:app --reload --port 8000
```

The SQLite database (`geo_auditor.db`) is created automatically on startup.

## Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

## Example request

```bash
curl -X POST http://localhost:8000/audits \
  -H "Content-Type: application/json" \
  -d '{"brand_name": "Stripe", "url": "https://stripe.com"}'
```

Returns the full audit result (composite score, sub-scores, bot-access table,
per-prompt mention rates with raw responses, retrieval result, and
recommendations) as one JSON object.

## API endpoints

| Method | Path            | Description                                        |
|--------|-----------------|----------------------------------------------------|
| POST   | `/audits`       | Run the full pipeline synchronously, return result |
| GET    | `/audits/{id}`  | Fetch a stored audit's full joined result          |
| GET    | `/audits`       | List past audits (history)                         |
| GET    | `/health`       | Liveness + whether Exa is enabled                  |

## Scoring

Composite weights (in `scoring_engine.py`):

| Signal    | Weight |
|-----------|--------|
| access    | 15%    |
| technical | 20%    |
| mention   | 50%    |
| retrieval | 15%    |

AI visibility (`mention`) carries the most weight — it is the entire point of
the tool. Technical readiness and crawler access are *enablers* of visibility,
not proof of it, so a perfectly-built page for a brand no AI model knows still
scores low.

When Exa is unavailable, the retrieval weight is redistributed proportionally
across the other three signals.

### How AI visibility is measured (hallucination-aware)

A naive "does the brand name appear in the response" check is misleading:
branded prompts echo the name, and models happily hallucinate confident-sounding
answers about brands they've never heard of. Instead, `ai_query_simulator.py`
measures **genuine** visibility:

1. **Category inference** — the brand's market category is inferred from page
   content via the model, with the brand name explicitly stripped out so
   unbranded prompts stay unbranded.
2. **Knowledge grounding + hallucination detection** — the model is asked
   factual questions about the brand several times. If the answers are mutually
   *consistent*, the brand is genuinely `known`. If the model invents
   contradictory stories each time (e.g. "it's malware" / "it's a YouTuber"),
   that is `hallucinated`, not visibility. If it explicitly says it doesn't
   know, it is `unknown`.
3. **Organic discovery** — unbranded category prompts ask the model to list
   leading names; a match means the model surfaced the brand *on its own*. This
   is the strongest visibility signal and is weighted most heavily.

The mention score is **knowledge-gated**: `hallucinated` and `unknown` brands
are capped low, and the overall composite is also capped for them (a brand the
model doesn't truly know cannot be "highly visible" regardless of page quality).

### Multiple AI providers (Gemini / OpenAI / Claude)

Provider selection is controlled by `AI_PROVIDER` (default `gemini`). The model
layer is provider-agnostic: `ai_query_simulator.py` defines an `LLMProvider`
protocol and a `PROVIDERS` registry. To add OpenAI or Claude, implement a class
with an async `generate(client, prompt) -> str` method, register it in
`PROVIDERS`, add its API key to the environment, and set `AI_PROVIDER`. Only
Gemini is wired in by default.

Access penalties are **category-aware**: blocking a search/retrieval bot
(`OAI-SearchBot`, `PerplexityBot`, `ClaudeBot`) costs far more than blocking a
training-only bot (`GPTBot`, `Google-Extended`, `CCBot`, `Bytespider`),
because blocking training does not make a page invisible to AI answers.

Every recommendation is tied to a specific stored check — no generic filler.

## Notes / out of scope

Per the build spec, the following are intentionally **not** included:
authentication, multiple AI providers, a job queue / background workers,
PostgreSQL, competitor tracking, scheduled audits, CSV export, or a design
system beyond Tailwind utilities. The `GET /audits` history endpoint exists for
future use but there is no history-browsing UI.

## Troubleshooting

### Rate Limiting (429 errors)
If you see `429` errors in the logs, you've hit the Gemini API rate limit:
- **Free tier**: Has very low rate limits
- **Solution**: Wait a few minutes and try again, or upgrade your API plan
- The code automatically retries transient 429 errors with exponential backoff

### Model Not Found (404 errors)
If you see `404 model not found` errors:
- Check that `GEMINI_MODEL` in your environment matches an available model
- Default is `gemini-3.8-flash` (as of October 2024)
- Gemini models change over time; check https://ai.google.dev/ for current models

### Audit Returns Low Scores
If audits complete but show very low AI visibility scores:
- Check the logs for API errors (look for `[ai]` prefixed messages)
- Verify your `GEMINI_API_KEY` is valid
- Ensure you have sufficient API quota remaining
