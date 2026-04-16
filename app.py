import os
import re
import json
import logging
import datetime
import subprocess

from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv

import vertexai
from vertexai.generative_models import GenerativeModel

# --- 1. Load environment variables ---
load_dotenv()

# --- 2. Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# --- 3. Flask App ---
app = Flask(__name__)

# --- 4. Configuration from .env ---
BQ_PROD_PROJECT = os.environ.get("BQ_PROD_PROJECT", "")
BQ_EXECUTABLE_PATH = os.environ.get("BQ_EXECUTABLE_PATH", "")
BQ_DATASET = os.environ.get("BQ_DATASET", "")
CUSTOMER_LOOKUP_TABLE = os.environ.get("CUSTOMER_LOOKUP_TABLE", "")
BQ_MANUAL_REVIEW_TABLE = os.environ.get("BQ_MANUAL_REVIEW_TABLE", "")
LLM_DEV_PROJECT = os.environ.get("LLM_DEV_PROJECT", "")
LLM_LOCATION = os.environ.get("LLM_LOCATION", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.environ.get("FLASK_PORT", "5000"))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() == "true"

HTTP_PROXY = os.environ.get("HTTP_PROXY", "")
HTTPS_PROXY = os.environ.get("HTTPS_PROXY", "")
if HTTP_PROXY:
    os.environ["HTTP_PROXY"] = HTTP_PROXY
if HTTPS_PROXY:
    os.environ["HTTPS_PROXY"] = HTTPS_PROXY


# --- 5. Startup Validation ---
def validate_config():
    """Validate required configuration at startup. Fail fast with clear messages."""
    required = {
        "BQ_PROD_PROJECT": BQ_PROD_PROJECT,
        "BQ_EXECUTABLE_PATH": BQ_EXECUTABLE_PATH,
        "BQ_DATASET": BQ_DATASET,
        "BQ_MANUAL_REVIEW_TABLE": BQ_MANUAL_REVIEW_TABLE,
        "LLM_DEV_PROJECT": LLM_DEV_PROJECT,
        "LLM_LOCATION": LLM_LOCATION,
        "LLM_MODEL": LLM_MODEL,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        raise SystemExit(1)

    if not os.path.exists(BQ_EXECUTABLE_PATH):
        logger.error("BQ_EXECUTABLE_PATH does not exist: %s", BQ_EXECUTABLE_PATH)
        raise SystemExit(1)

    prompt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
    for fname in ("system_prompt.md", "user_prompt.md"):
        if not os.path.exists(os.path.join(prompt_dir, fname)):
            logger.error("Prompt file not found: prompts/%s", fname)
            raise SystemExit(1)

    logger.info("Configuration validated successfully.")


# --- 6. Load Prompts ---
def load_prompts():
    """Load system and user prompt templates from external .md files."""
    prompt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
    with open(os.path.join(prompt_dir, "system_prompt.md"), encoding="utf-8") as f:
        system_prompt = f.read()
    with open(os.path.join(prompt_dir, "user_prompt.md"), encoding="utf-8") as f:
        user_prompt_template = f.read()
    return system_prompt, user_prompt_template


validate_config()
SYSTEM_PROMPT, USER_PROMPT_TEMPLATE = load_prompts()

# --- 7. Initialize Vertex AI (once at startup) ---
vertexai.init(project=LLM_DEV_PROJECT, location=LLM_LOCATION)

# --- 8. LLM Response Cache ---
_llm_cache = {}


# --- 9. BigQuery CLI Helpers ---
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def run_bq_query(query):
    """Execute a BigQuery SQL query via the bq CLI and return parsed JSON rows."""
    cmd = [
        BQ_EXECUTABLE_PATH,
        "query",
        "--format=json",
        "--nouse_legacy_sql",
        "--quiet",
        query,
    ]
    logger.info("Running BQ query via CLI")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown bq error"
            logger.error("BQ query failed (exit %d): %s", result.returncode, error_msg)
            return {"error": f"BQ query failed: {error_msg}"}

        output = result.stdout.strip()
        if not output or output == "[]":
            return {"error": "BQ query returned 0 rows."}

        return json.loads(output)
    except subprocess.TimeoutExpired:
        logger.error("BQ query timed out after 120 seconds")
        return {"error": "BQ query timed out."}
    except json.JSONDecodeError as e:
        logger.error("Failed to parse BQ JSON output: %s", e)
        return {"error": f"Failed to parse BQ output: {e}"}
    except Exception as e:
        logger.error("Unexpected error running BQ query: %s", e)
        return {"error": f"Unexpected BQ error: {e}"}


def bq_insert_row(table, row_dict):
    """Insert a single row into a BigQuery table via the bq CLI streaming insert."""
    json_str = json.dumps(row_dict)
    cmd = [BQ_EXECUTABLE_PATH, "insert", table]
    logger.info("Inserting row into %s via BQ CLI", table)
    try:
        result = subprocess.run(
            cmd, input=json_str, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            error_msg = (
                result.stderr.strip() or result.stdout.strip() or "Unknown bq insert error"
            )
            logger.error("BQ insert failed (exit %d): %s", result.returncode, error_msg)
            return {"error": f"BQ insert failed: {error_msg}"}

        logger.info("Successfully inserted row into %s", table)
        return {"status": "ok"}
    except subprocess.TimeoutExpired:
        logger.error("BQ insert timed out after 60 seconds")
        return {"error": "BQ insert timed out."}
    except Exception as e:
        logger.error("Unexpected error during BQ insert: %s", e)
        return {"error": f"Unexpected BQ insert error: {e}"}


# --- 10. Data Fetch ---
def fetch_one_record(start_date, end_date):
    """
    Fetch a single random unreviewed record from BigQuery via bq CLI.
    Filters by session_start date range (inclusive).
    Excludes records already present in the manual review table.
    """
    if not DATE_PATTERN.match(start_date) or not DATE_PATTERN.match(end_date):
        return {"error": "Invalid date format. Use YYYY-MM-DD."}

    query = (
        "SELECT "
        "s.* EXCEPT (conversation_turns), "
        "turn.*, "
        "s.customer_json_data "
        "FROM "
        f"`{BQ_DATASET}.conversations` AS s, "
        "UNNEST(s.conversation_turns) AS turn "
        f"LEFT JOIN `{BQ_MANUAL_REVIEW_TABLE}` AS r "
        "ON s.session_id = r.SESSION_ID "
        "AND CAST(turn.turn_position AS STRING) = r.TURN_POSITION "
        "WHERE "
        "r.SESSION_ID IS NULL "
        f"AND s.session_start >= '{start_date}' "
        f"AND s.session_start <= '{end_date}' "
        "AND turn.turn_position > 1 "
        "AND turn.req IS NOT NULL "
        "AND turn.response_text IS NOT NULL "
        "AND s.customer_json_data IS NOT NULL "
        "ORDER BY rand() "
        "LIMIT 1"
    )

    result = run_bq_query(query)
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, list) and len(result) > 0:
        logger.info("Fetched 1 record from BigQuery")
        return result[0]
    return {"error": "BQ query returned 0 rows."}


# --- 11. LLM Analysis ---
def analyze_groundedness(question, answer, source_data):
    """Evaluate whether the agent answer is grounded in source data using Gemini."""
    user_prompt = USER_PROMPT_TEMPLATE.format(
        question=question,
        answer=answer,
        source_data=source_data,
    )
    try:
        model = GenerativeModel(LLM_MODEL, system_instruction=SYSTEM_PROMPT)
        response = model.generate_content(user_prompt)
        llm_text = response.text
        json_start = llm_text.find("{")
        json_end = llm_text.rfind("}")
        if json_start != -1 and json_end != -1:
            return json.loads(llm_text[json_start : json_end + 1])
        logger.warning("Could not extract JSON from LLM response")
        return {
            "is_correct": None,
            "reasoning": f"Could not parse JSON from LLM response: {llm_text}",
        }
    except Exception as e:
        logger.error("LLM API error: %s", e)
        return {"is_correct": None, "reasoning": f"LLM API Error: {e}"}


# --- 12. Flask Routes ---
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/get-record")
def get_record():
    """Fetch a single random unreviewed record from BigQuery. No LLM call."""
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    if not start_date or not end_date:
        return jsonify({"error": "Select a date range and click Get Record."}), 400

    logger.info("/get-record called for %s to %s", start_date, end_date)
    record = fetch_one_record(start_date, end_date)

    if record.get("error"):
        return jsonify({"error": record["error"]}), 500

    return jsonify({"record": record})


@app.route("/llm-review", methods=["POST"])
def llm_review():
    """Run LLM groundedness analysis on a record. Returns evaluation JSON."""
    data = request.get_json()
    question = data.get("req", "")
    answer = data.get("response_text", "")
    source_data = data.get("customer_json_data", "")
    session_id = data.get("session_id", "")
    turn_position = str(data.get("turn_position", ""))

    if not question or not answer or not source_data:
        return jsonify({"is_correct": None, "reasoning": "Missing data for LLM review."}), 400

    cache_key = (session_id, turn_position)
    if session_id and turn_position and cache_key in _llm_cache:
        logger.info("LLM cache hit for session %s turn %s", session_id, turn_position)
        return jsonify(_llm_cache[cache_key])

    logger.info("Running LLM review for session %s turn %s", session_id, turn_position)
    evaluation = analyze_groundedness(question, answer, source_data)

    if session_id and turn_position:
        _llm_cache[cache_key] = evaluation

    return jsonify(evaluation)


@app.route("/save-response", methods=["POST"])
def save_response():
    """Save reviewer feedback and LLM verdict to BigQuery via bq CLI."""
    data = request.get_json()
    row = {
        "SESSION_ID": data.get("session_id", ""),
        "TURN_POSITION": str(data.get("turn_position", "")),
        "CUSTOMER_ID": data.get("customer_id", ""),
        "USER_EMAIL": data.get("user_email", ""),
        "RESPONSE_SOURCE": data.get("response_source", ""),
        "LOOKUP_STATUS": data.get("lookup_status", ""),
        "USER_RESPONSE": data.get("user_response", ""),
        "USER_REASON": data.get("user_reason", ""),
        "LLM_IS_CORRECT": data.get("llm_is_correct"),
        "LLM_HAS_SAFETY_VIOLATION": data.get("llm_has_safety_violation"),
        "LLM_HAS_BRAND_VIOLATION": data.get("llm_has_brand_violation"),
        "LLM_REASONING": data.get("llm_reasoning", ""),
        "ingestion_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    result = bq_insert_row(BQ_MANUAL_REVIEW_TABLE, row)
    if result.get("error"):
        return jsonify(result), 500
    return jsonify(result)


@app.route("/health")
def health():
    """Health check. Verifies BQ CLI connectivity."""
    test = run_bq_query("SELECT 1 AS ok")
    if isinstance(test, dict) and test.get("error"):
        return jsonify({"status": "error", "detail": test["error"]}), 503
    return jsonify({"status": "ok"})


# --- 13. Main ---
if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
