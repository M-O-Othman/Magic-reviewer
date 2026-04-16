# Action Plan — Magic Reviewer Enhancements

## Constraints (do not change)
- Proxy/authentication method stays as-is
- All BigQuery operations must use the `bq` CLI executable (subprocess), not the Python `bigquery.Client` API
- Single `app.py` file structure — no module splitting
- Keep current worker-matching LLM prompt (no Judge harness adoption)
- Reviewer identity is out of scope
- Stats dashboard is out of scope (BI team owns it)

---

## Phase 1: Critical Bug Fixes

### Task 1.1 — Replace BigQuery Python client with `bq` CLI subprocess calls
**Why**: The org does not allow direct BQ API access. Current code uses `bigquery.Client()` which violates this constraint.
**What**:
- Remove `from google.cloud import bigquery` and `bq_client = bigquery.Client(...)` initialization
- Remove `from google.api_core import exceptions as google_exceptions`
- Create a helper function `run_bq_query(query)` that:
  - Calls `subprocess.run()` with `BQ_EXECUTABLE_PATH`
  - Passes `--format=json`, `--quiet`, and the query
  - Parses the JSON stdout into a Python dict/list
  - Handles errors (non-zero exit code, stderr)
- Create a helper function `bq_insert_row(table, row_dict)` that:
  - Uses `bq insert` command with JSON payload via stdin
  - Handles errors
- Rewrite `fetch_one_record_from_bigquery()` to use `run_bq_query()`
- Rewrite `save_response()` to use `bq_insert_row()`
- Update `install.sh` / `install.bat` — remove `google-cloud-bigquery` from pip install

### Task 1.2 — Add separate `/llm-review` POST endpoint
**Why**: Frontend calls `/llm-review` but it doesn't exist. Separating data fetch from LLM review gives faster perceived load time.
**What**:
- Add `@app.route('/llm-review', methods=['POST'])` that:
  - Accepts JSON body with `req`, `response_text`, `customer_json_data`
  - Calls `analyze_groundedness_with_gemini()`
  - Returns the LLM evaluation JSON
- Modify `/get-record` to only fetch and return the BQ record (no LLM call)
- Frontend already calls `/llm-review` as background POST — just needs the backend endpoint

### Task 1.3 — Wire date range into BQ query
**Why**: Date picker UI exists but query ignores it. Reviewers need to audit specific time windows.
**What**:
- Modify `BQ_QUERY_TEMPLATE` to accept `session_start` date filter:
  ```sql
  WHERE session_start >= '{start_date}'
    AND session_start <= '{end_date}'
    AND turn.turn_position > 1
    AND ...
  ```
- Pass `start_date` and `end_date` from `/get-record` request params into the query
- Use parameterized query or proper escaping to prevent SQL injection
- Range is inclusive on both ends

### Task 1.4 — Move `vertexai.init()` to app startup
**Why**: Currently called on every LLM request (line 226). Wasteful and could cause issues.
**What**:
- Move `vertexai.init(project=LLM_DEV_PROJECT, location=LLM_LOCATION)` to the module-level initialization section (after env loading)
- Remove it from `analyze_groundedness_with_gemini()`

### Task 1.5 — Remove dead code and unused imports
**Why**: Clean up after BQ client removal and endpoint restructuring.
**What**:
- Remove `google.cloud.bigquery` import
- Remove `google.api_core.exceptions` import
- Remove `bq_client` global variable
- Verify `BQ_EXECUTABLE_PATH` is now actually used (it was loaded but unused before)

---

## Phase 2: Core Enhancements

### Task 2.1 — Duplicate review prevention
**Why**: Without this, reviewers waste time on already-reviewed records.
**What**:
- Modify `BQ_QUERY_TEMPLATE` to LEFT JOIN against `BQ_MANUAL_REVIEW_TABLE`:
  ```sql
  LEFT JOIN `{review_table}` AS r
    ON s.session_id = r.SESSION_ID
    AND turn.turn_position = r.TURN_POSITION
  WHERE r.SESSION_ID IS NULL
    AND ...
  ```
- This excludes any session_id + turn_position combo that already has a review entry

### Task 2.2 — Save LLM verdict alongside human verdict
**Why**: Enables LLM-vs-human agreement analysis (the core metric for trusting the LLM). BI team needs this data.
**What**:
- Expand the `/save-response` payload to include:
  - `LLM_IS_CORRECT` (boolean)
  - `LLM_HAS_SAFETY_VIOLATION` (boolean)
  - `LLM_HAS_BRAND_VIOLATION` (boolean)
  - `LLM_REASONING` (string)
- Frontend stores the LLM result after `/llm-review` returns and includes it in the save payload
- Update `bq_insert_row` to include these fields
- Note: BQ table schema may need to be updated separately by the BI team to add these columns

### Task 2.3 — Externalize prompts to .md files
**Why**: System prompt is 104 lines and user prompt is 24 lines embedded in app.py. Externalizing makes prompt iteration faster without code changes.
**What**:
- Create `prompts/system_prompt.md` — move the SYSTEM_PROMPT content there
- Create `prompts/user_prompt.md` — move the USER_PROMPT_TEMPLATE content there
- At app startup, read both files into variables
- Keep `{question}`, `{answer}`, `{source_data}` as format placeholders in the user prompt file

### Task 2.4 — Configuration validation at startup
**Why**: App currently crashes with unhelpful KeyError if an env var is missing.
**What**:
- Add a `validate_config()` function called at startup
- Check all required env vars exist and are non-empty
- Check `BQ_EXECUTABLE_PATH` points to an existing file
- Check prompt files exist
- Print clear error message and exit if validation fails

### Task 2.5 — Structured logging
**Why**: `print()` statements are not searchable, filterable, or timestamped in production.
**What**:
- Import `logging` and configure at startup with format: `[%(asctime)s] %(levelname)s: %(message)s`
- Replace all `print()` calls with appropriate `logging.info()`, `logging.error()`, `logging.warning()`
- Add request context where useful (session_id, turn_position)

---

## Phase 3: Frontend UX

### Task 3.1 — Fix frontend error handling for save
**Why**: Save errors are silently swallowed (line 147 catch just logs to console). Reviewer doesn't know if their vote was lost.
**What**:
- Check response status from `/save-response`
- On failure, show error message in `feedback-message` element
- On success, show confirmation as it currently does

### Task 3.2 — Add free-text "reason for NO" input
**Why**: Creates feedback loop — disagreements can be analyzed to improve the LLM prompt.
**What**:
- Add a text input that appears when "No" is clicked
- Add a "Submit" button next to it
- Include the reason text in the `/save-response` payload as `USER_REASON`
- Note: BQ table schema may need a new column

### Task 3.3 — Keyboard shortcuts
**Why**: For high-volume review work, clicking is slow. Keyboard shortcuts dramatically speed up throughput.
**What**:
- `Y` key = Yes
- `N` key = No
- `S` or `Space` = Skip / Get Another Record
- Only active when no text input is focused
- Show shortcut hints on the buttons: "Yes (Y)", "No (N)", "Get Another (S)"

### Task 3.4 — Auto-advance after vote
**Why**: Removes one click per review cycle.
**What**:
- After Yes/No is clicked and save completes, automatically fetch the next record after a brief delay (1-2 seconds) so the reviewer sees the confirmation
- Show a brief "Saved. Loading next..." message
- Skip button already does this (calls fetchAndDisplayRecord)

### Task 3.5 — Review counter
**Why**: Gives reviewers a sense of progress.
**What**:
- Add a counter in the header area: "Reviews this session: X"
- Increment on each Yes/No save
- Stored in JS variable (resets on page reload — that's fine)

### Task 3.6 — Collapsible source data with search
**Why**: JSON blobs can be massive and hard to navigate.
**What**:
- Add a search/filter input above the source data card
- Highlight matches within the JSON
- Optional: collapsible nested objects (could use a simple toggle approach)

---

## Phase 4: Robustness

### Task 4.1 — Health check endpoint
**Why**: Useful for monitoring and load balancers.
**What**:
- Add `@app.route('/health')` that:
  - Runs a trivial BQ query (`SELECT 1`) via CLI to verify connectivity
  - Returns `{"status": "ok"}` or `{"status": "error", "detail": "..."}`

### Task 4.2 — Frontend rate limiting / debounce
**Why**: Prevent accidental rapid-fire clicks from spawning multiple BQ + LLM calls.
**What**:
- Disable all action buttons while a fetch or save is in progress (partially done already for fetch, not for save)
- Add a cooldown period after save before allowing another action
- Prevent double-click on Yes/No

### Task 4.3 — LLM response caching
**Why**: If the same record is fetched again, avoid re-calling Gemini. Saves cost and latency.
**What**:
- Add a simple in-memory dict cache keyed by `(session_id, turn_position)`
- Check cache before calling Gemini in `/llm-review`
- No TTL needed — cached results are deterministic for the same input
- Cache clears on app restart (acceptable)

### Task 4.4 — Add basic tests
**Why**: Zero tests currently. Prevents regressions as enhancements are added.
**What**:
- Test BQ CLI helper: mock subprocess, verify query construction and JSON parsing
- Test LLM JSON parsing: feed known LLM output strings, verify extraction
- Test `/save-response` payload schema construction
- Test date range SQL injection prevention
- Test prompt file loading

---

## Execution Order

1. Phase 1 (bugs) — all tasks, in order 1.1 through 1.5
2. Phase 2 (core) — tasks 2.3, 2.5, 2.4, 2.1, 2.2
3. Phase 3 (UX) — tasks 3.1, 3.3, 3.5, 3.2, 3.4, 3.6
4. Phase 4 (robustness) — tasks 4.2, 4.1, 4.3, 4.4

Estimated total: ~18 tasks across 4 phases.
