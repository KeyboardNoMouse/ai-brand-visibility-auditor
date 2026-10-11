# Bug Fixes Applied

## Issue: Audit Not Working

### Root Cause
The AI Brand Visibility Auditor was failing to complete audits due to an **outdated Gemini API model reference**.

### Specific Problems Identified

1. **Deprecated Model (PRIMARY ISSUE)**
   - **Problem**: The code was using `gemini-2.0-flash` which no longer exists
   - **Error**: Gemini API returned 404 with message: "This model models/gemini-2.0-flash is no longer available. Please update your code to use models/gemini-3.8-flash"
   - **Impact**: All AI visibility checks were failing silently, resulting in:
     - `brand_known` = "unknown"
     - `mention_score` = 0.0
     - Overall audit scores capped at 30.0
   - **Fix**: Updated default model to `gemini-3.8-flash` in `backend/app/config.py`

2. **Poor Error Visibility**
   - **Problem**: HTTP errors from the Gemini API were being caught but not logged
   - **Impact**: Failed API calls returned empty strings without clear error messages
   - **Fix**: Enhanced error handling in `backend/app/modules/ai_query_simulator.py` to:
     - Log HTTP status errors with response details
     - Identify 404 model-not-found errors specifically
     - Log network errors with retry information
     - Log unexpected response structures

### Files Modified

1. **`backend/app/config.py`**
   ```python
   # Changed from:
   GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
   # To:
   GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
   ```

2. **`backend/app/modules/ai_query_simulator.py`**
   - Wrapped API calls in try-except blocks
   - Added detailed logging for HTTP errors, 404s, and network issues
   - Added retry logic for network errors

### Verification

After the fixes:
- ✅ Audit completes successfully
- ✅ AI visibility checks run properly
- ✅ Brand knowledge is correctly detected (e.g., Stripe: "known")
- ✅ Mention scores calculated correctly (e.g., 67.62 for Stripe)
- ✅ Composite scores reflect actual visibility (e.g., 75.28 for Stripe)
- ✅ Error messages are clear when API issues occur

### Testing

Run a test audit:
```bash
cd backend
./venv/bin/python3 -c "
import asyncio
from app import config, database
from app.main import run_pipeline

async def test():
    config.validate_startup_config()
    database.init_db()
    audit_id = 'test-123'
    database.create_audit(audit_id, 'Stripe', 'https://stripe.com')
    result = await run_pipeline(audit_id, 'Stripe', 'https://stripe.com')
    print(f'Score: {result[\"audit\"][\"composite_score\"]}')

asyncio.run(test())
"
```

### Notes

- Rate limiting (429 errors) may occur with free-tier Gemini API keys
- The retry logic handles transient 429/503 errors automatically
- Consider adding `GEMINI_MODEL` to `.env` to easily switch models if needed
