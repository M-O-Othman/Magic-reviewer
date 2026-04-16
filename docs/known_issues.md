# Known Issues

## Fixed in Current Version

- **Missing /llm-review endpoint** (app.py): Frontend called `/llm-review` but the route did not exist. The LLM review was bundled into `/get-record`, causing the UI to show "LLM review failed" after already waiting for the LLM call. Fixed by adding a separate `/llm-review` POST endpoint and removing the LLM call from `/get-record`.

- **Date range not wired** (app.py): Date picker UI collected dates but the BQ query ignored them (`ORDER BY rand() LIMIT 1` with no date filter). Fixed by adding `session_start` range filter (inclusive) to the query.

- **vertexai.init() called per request** (app.py): `vertexai.init()` was called inside `analyze_groundedness_with_gemini()` on every LLM request. Moved to module-level startup.

- **BQ_EXECUTABLE_PATH loaded but unused** (app.py): The env var was required at startup but never referenced. Now all BQ operations use it via subprocess.

- **datetime.utcnow() deprecation** (app.py): Replaced with `datetime.now(datetime.timezone.utc)`.

- **Save errors silently swallowed** (index.html): The `saveResponse()` catch block only logged to console. Reviewers had no indication their vote was lost. Fixed by showing error messages in the UI.

## Current Limitations

- **BQ review table schema**: The `/save-response` endpoint now sends additional fields (`USER_REASON`, `LLM_IS_CORRECT`, `LLM_HAS_SAFETY_VIOLATION`, `LLM_HAS_BRAND_VIOLATION`, `LLM_REASONING`). The BigQuery table schema must be updated to include these columns, otherwise inserts may fail or silently drop the new fields.

- **LLM cache is in-memory only**: The cache resets on app restart. Acceptable for the current use case but means repeated reviews of the same record after restart will re-call Gemini.

- **No reviewer identity**: The app does not track who is reviewing. The `user_email` field stores the chatbot questioner's email, not the reviewer's.
