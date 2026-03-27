import os
import subprocess
import json
import locale
from flask import Flask, render_template, jsonify, request
import google.generativeai as genai
from dotenv import load_dotenv

# --- 1. Load environment variables ---
load_dotenv()

# --- 2. Flask App Initialization ---
app = Flask(__name__)

# --- 3. Configuration from .env ---
BQ_PROD_PROJECT = os.environ["BQ_PROD_PROJECT"]
LLM_DEV_PROJECT = os.environ["LLM_DEV_PROJECT"]
LLM_LOCATION = os.environ["LLM_LOCATION"]
LLM_MODEL = os.environ["LLM_MODEL"]
BQ_EXECUTABLE_PATH = os.environ["BQ_EXECUTABLE_PATH"]
BQ_DATASET = os.environ["BQ_DATASET"]
CUSTOMER_LOOKUP_TABLE = os.environ["CUSTOMER_LOOKUP_TABLE"]
FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.environ.get("FLASK_PORT", "5000"))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() == "true"

HTTP_PROXY = os.environ.get("HTTP_PROXY", "")
HTTPS_PROXY = os.environ.get("HTTPS_PROXY", "")
if HTTP_PROXY:
    os.environ["HTTP_PROXY"] = HTTP_PROXY
if HTTPS_PROXY:
    os.environ["HTTPS_PROXY"] = HTTPS_PROXY

# --- 4. BigQuery and LLM Logic ---
BQ_QUERY_TEMPLATE = """
WITH
src AS (
  SELECT REGEXP_EXTRACT(conversation_name, r'sessions/([^/]+)') AS session_id, conversation_name, turn_position, request_time, LOWER(TRIM(LAX_STRING(request.queryParams.parameters.customer_id))) AS customer_id, LOWER(TRIM(LAX_STRING(request.queryParams.parameters.user_id))) AS user_email, LAX_STRING(request.queryInput.text.text) AS req, response.queryResult.responseMessages AS response_messages, response.queryResult.generativeInfo.actionTracingInfo.actions AS actions
  FROM `{dataset}.prep_packs_agent_conversation_export`
  WHERE request_time >= TIMESTAMP('{start_date} 00:00:00+00') AND request_time < TIMESTAMP('{end_date} 00:00:00+00')
),
per_turn AS (
  SELECT session_id, turn_position, request_time, customer_id, user_email, req, (SELECT STRING_AGG(LAX_STRING(m.text.text[0]), "\\n") FROM UNNEST(JSON_QUERY_ARRAY(response_messages)) AS m WHERE LAX_STRING(m.source) = 'VIRTUAL_AGENT') AS response_text, (SELECT AS STRUCT ANY_VALUE(JSON_VALUE(a.toolUse.outputActionParameters, '$."200".sessionInfo.parameters.response_source')) AS response_source, ANY_VALUE(JSON_VALUE(a.toolUse.outputActionParameters, '$."200".sessionInfo.parameters.lookup_status')) AS lookup_status FROM UNNEST(JSON_QUERY_ARRAY(actions)) AS a WHERE a.toolUse IS NOT NULL) AS act
  FROM src
),
session_info AS (
  SELECT session_id, ARRAY_AGG(customer_id IGNORE NULLS ORDER BY request_time LIMIT 1)[OFFSET(0)] AS session_customer_id, ARRAY_AGG(user_email IGNORE NULLS ORDER BY request_time LIMIT 1)[OFFSET(0)] AS session_user_email FROM src GROUP BY session_id
),
customer_latest AS (
  SELECT * EXCEPT(rn) FROM (SELECT a.*, ROW_NUMBER() OVER (PARTITION BY a.customer_id ORDER BY a.snapshot_date DESC) AS rn FROM `{customer_lookup_table}` a) WHERE rn = 1
)
SELECT pt.session_id, si.session_customer_id AS customer_id, si.session_user_email AS user_email, pt.req, pt.response_text, pt.act.response_source, pt.act.lookup_status, c.data AS customer_json_data, pt.turn_position, pt.request_time
FROM per_turn AS pt LEFT JOIN session_info AS si ON pt.session_id = si.session_id LEFT JOIN customer_latest AS c ON SAFE_CAST(si.session_customer_id AS INT64) = c.customer_id
WHERE pt.act.response_source IS NOT NULL AND pt.act.lookup_status IS NOT NULL ORDER BY RAND() LIMIT 1;
"""

def fetch_one_record_from_bigquery(start_date, end_date):
    query = BQ_QUERY_TEMPLATE.format(
        dataset=BQ_DATASET,
        customer_lookup_table=CUSTOMER_LOOKUP_TABLE,
        start_date=start_date,
        end_date=end_date
    )
    try:
        command = [BQ_EXECUTABLE_PATH, "query", "--project_id", BQ_PROD_PROJECT, "--format=json", "--use_legacy_sql=false"]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout_bytes, stderr_bytes = process.communicate(input=query.encode('utf-8'))
        system_encoding = locale.getpreferredencoding()
        stdout = stdout_bytes.decode(system_encoding, errors='ignore')
        stderr = stderr_bytes.decode(system_encoding, errors='ignore')
        if process.returncode != 0: return {"error": f"bq command failed: {stderr}"}
        json_start = stdout.find('[')
        if json_start == -1: return {"error": "No JSON found in bq output."}
        data = json.loads(stdout[json_start:])
        return data[0] if data else {"error": "BQ query returned 0 rows."}
    except FileNotFoundError: return {"error": f"Server Error: Could not find bq.cmd at {BQ_EXECUTABLE_PATH}. Check BQ_EXECUTABLE_PATH in .env."}
    except Exception as e: return {"error": f"An unexpected error occurred: {e}"}

def analyze_groundedness_with_gemini(question, answer, source_data):
    prompt = f"""
You are a strict data auditor. Your task is to evaluate if the AGENT'S ANSWER is a correct and factually supported response to the USER'S QUESTION, based *strictly* on the provided GROUND TRUTH DATA.

**RULES:**
- Your evaluation must be based **only** on the information in the `GROUND TRUTH DATA`.
- If the answer contains information not found in the data, it is INCORRECT.
- The answer is CORRECT only if every piece of information is directly verifiable from the data.

**DATA FOR EVALUATION:**
[USER'S QUESTION]: {question}
[AGENT'S ANSWER]: {answer}
[GROUND TRUTH DATA]: ```json
{source_data}
```
---
**FINAL OUTPUT:**
Respond with only a single JSON object containing three keys:
1. "is_correct": a boolean (`true` or `false`).
2. "reasoning": a concise, one-sentence explanation for your verdict.
3. "marked_source_data": an exact replica of the source data with marker tags <Marked> and </Marked> indicating the parts relevant to the question and answer.

"""
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel
        vertexai.init(project=LLM_DEV_PROJECT, location=LLM_LOCATION)
        model = GenerativeModel(LLM_MODEL)
        response = model.generate_content(prompt)

        llm_text = response.text
        json_start = llm_text.find('{')
        json_end = llm_text.rfind('}')
        if json_start != -1 and json_end != -1:
            clean_json_string = llm_text[json_start : json_end + 1]
            return json.loads(clean_json_string)
        else:
            return {"is_correct": None, "reasoning": "Could not parse JSON from LLM response."}

    except Exception as e:
        print(f"--- LLM EXCEPTION --- Error: {e}")
        return {"is_correct": None, "reasoning": f"LLM API Error: {e}"}

# --- 5. Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get-record')
def get_record():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if not start_date or not end_date:
        return jsonify({"error": "Please select a date range and click 'Get Record'."}), 400

    print(f"--- SERVER: /get-record called with range {start_date} to {end_date} ---")
    bq_record = fetch_one_record_from_bigquery(start_date, end_date)

    if bq_record.get("error"):
        return jsonify({"error": bq_record.get("error")}), 500

    llm_evaluation = {"is_correct": None, "reasoning": "Data missing for LLM review."}
    if bq_record.get('req') and bq_record.get('response_text') and bq_record.get('customer_json_data'):
        llm_evaluation = analyze_groundedness_with_gemini(bq_record['req'], bq_record['response_text'], bq_record['customer_json_data'])

    full_data = {
        "record": bq_record,
        "llm_review": llm_evaluation
    }
    print("--- SERVER: Successfully prepared data. Sending to frontend. ---")
    return jsonify(full_data)

RESPONSE_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_response.json")

@app.route('/save-response', methods=['POST'])
def save_response():
    data = request.get_json()
    entry = {
        "SESSION_ID": data.get("session_id", ""),
        "TURN_POSITION": data.get("turn_position", ""),
        "CUSTOMER_ID": data.get("customer_id", ""),
        "USER_EMAIL": data.get("user_email", ""),
        "RESPONSE_SOURCE": data.get("response_source", ""),
        "LOOKUP_STATUS": data.get("lookup_status", ""),
        "USER_RESPONSE": data.get("user_response", "")
    }
    try:
        existing = []
        if os.path.exists(RESPONSE_LOG_FILE):
            with open(RESPONSE_LOG_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        existing.append(entry)
        with open(RESPONSE_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"--- Error saving response: {e} ---")
        return jsonify({"error": str(e)}), 500

# --- 6. Main execution block ---
if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
