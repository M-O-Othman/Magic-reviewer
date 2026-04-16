# Magic Reviewer

An application for reviewing and validating AI agent responses against ground truth customer data.
It fetches random conversation records from BigQuery via the `bq` CLI, uses an LLM (Gemini via Vertex AI) to evaluate answer correctness, and presents everything in a reviewer-friendly UI with highlighted source data.

## Features

- **Date-range filtering**: Select a date range to query conversation records by `session_start`
- **Random record sampling**: Fetches a random unreviewed conversation turn within the selected range
- **Duplicate prevention**: Already-reviewed records are excluded automatically via LEFT JOIN against the review table
- **LLM-powered review**: Evaluates agent answers against source data using Gemini, with correctness verdict and reasoning
- **Highlighted source data**: Relevant fields are highlighted (green for correct, yellow for incorrect)
- **Source data search**: Filter and jump to specific fields in the JSON source data
- **Human validation**: Reviewers confirm or reject with Yes/No buttons, with optional free-text reasoning for rejections
- **LLM verdict logging**: Both the human verdict and the LLM verdict are saved to BigQuery for agreement analysis
- **Keyboard shortcuts**: Y (Yes), N (No), S (Skip) for fast reviewing
- **Auto-advance**: Automatically loads the next record after voting
- **Session review counter**: Tracks how many records you have reviewed this session
- **Health check**: `/health` endpoint verifies BQ CLI connectivity
- **LLM response caching**: Avoids re-calling Gemini for the same record
- **Responsive UI**: Works on desktop, tablet, and mobile screens

## Prerequisites

- Python 3.8+
- Google Cloud SDK with `bq` CLI tool installed and authenticated (`gcloud auth application-default login`)
- Access to the configured BigQuery dataset and Vertex AI project

## Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/M-O-Othman/Magic-reviewer.git
   cd Magic-reviewer
   ```

2. **Install dependencies**:

   Linux/Mac:
   ```bash
   ./install.sh
   ```
   Windows:
   ```batch
   install.bat
   ```
   Or manually:
   ```bash
   pip install flask flask-cors google-cloud-aiplatform python-dotenv
   ```

3. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and fill in your project-specific values:

   | Variable | Description |
   |---|---|
   | `BQ_PROD_PROJECT` | GCP project ID for BigQuery queries |
   | `BQ_EXECUTABLE_PATH` | Full path to the `bq` CLI tool (e.g. `C:\...\bq.cmd`) |
   | `BQ_DATASET` | Fully qualified BigQuery dataset (`project.dataset`) |
   | `CUSTOMER_LOOKUP_TABLE` | Fully qualified customer lookup table path |
   | `BQ_MANUAL_REVIEW_TABLE` | Fully qualified table for storing review results |
   | `LLM_DEV_PROJECT` | GCP project ID for Vertex AI / Gemini |
   | `LLM_LOCATION` | Vertex AI region (e.g. `europe-west4`) |
   | `LLM_MODEL` | Gemini model name (e.g. `gemini-2.5-pro`) |
   | `HTTP_PROXY` / `HTTPS_PROXY` | Proxy URLs (leave empty if not required) |
   | `FLASK_HOST` | Host to bind Flask to (default: `0.0.0.0`) |
   | `FLASK_PORT` | Port for the Flask server (default: `5000`) |
   | `FLASK_DEBUG` | Enable debug mode (default: `true`) |

4. **Run the application**:
   ```bash
   python app.py
   ```

5. **Open in browser**: Navigate to `http://localhost:5000`

## Usage

1. Select a **From** and **To** date range (defaults to yesterday-today)
2. Click **Get Record** to fetch a random unreviewed conversation record
3. Review the **User Question**, **Agent Answer**, and **Source Data**
4. Use the search box above Source Data to find specific fields
5. Check the **LLM Review Opinion** for the automated assessment
6. Click **Yes (Y)** to agree or **No (N)** to disagree with the agent answer
7. When clicking No, provide a reason in the text field that appears
8. The next record loads automatically after voting
9. Click **Skip (S)** to skip without voting

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Y` | Vote Yes |
| `N` | Vote No (opens reason input) |
| `S` | Skip and load next record |

Shortcuts are disabled when a text input is focused.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve the reviewer UI |
| GET | `/get-record?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` | Fetch a random unreviewed record |
| POST | `/llm-review` | Run LLM groundedness analysis on a record |
| POST | `/save-response` | Save reviewer feedback and LLM verdict to BigQuery |
| GET | `/health` | Health check (verifies BQ CLI connectivity) |

## Testing

```bash
pip install pytest
python -m pytest tests/ -v
```

## Project Structure

```
Magic-reviewer/
├── app.py                 # Flask backend: routes, BQ CLI helpers, LLM integration
├── prompts/
│   ├── system_prompt.md   # LLM system prompt (externalized for easy iteration)
│   └── user_prompt.md     # LLM user prompt template
├── templates/
│   └── index.html         # Frontend template with review interface
├── Static/
│   ├── banner.jpg         # HSBC banner image
│   └── css/
│       └── style.css      # UI styling and responsive breakpoints
├── tests/
│   └── test_app.py        # Test suite (23 tests)
├── .env.example           # Environment variable template
├── install.sh             # Linux/Mac dependency installer
├── install.bat            # Windows dependency installer
├── .gitignore             # Git ignore rules
└── README.md              # This file
```
