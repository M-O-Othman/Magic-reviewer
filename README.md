# Magic Reviewer

An application for reviewing and validating AI agent responses against ground truth customer data. 
It fetches a random conversation records from BigQuery, uses an LLM (Gemini) to evaluate answer correctness, and presents everything in a reviewer-friendly UI with highlighted source data.

## Features

- **Date-range filtering**: Select a date range to query conversation records from BigQuery
- **Random record sampling**: Fetches a random agent conversation turn within the selected date range
- **LLM-powered review**: Automatically evaluates agent answers against source data using Gemini, with a correctness verdict and reasoning
- **Highlighted source data**: Relevant parts of the source data are highlighted — green for correct answers, red/yellow for incorrect
- **Human validation**: Reviewers can confirm or reject the agent's answer with Yes/No buttons
- **Response logging**: All reviewer feedback is saved to `user_response.json` for analysis
- **Responsive UI**: Works on desktop, tablet, and mobile screens

## Prerequisites

- Python 3.8+
- Google Cloud SDK with `bq` CLI tool installed and authenticated
- Access to the configured BigQuery dataset and Vertex AI project

## Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/M-O-Othman/Magic-reviewer.git
   cd Magic-reviewer
   ```

2. **Install dependencies**:
   ```bash
   pip install flask google-genai python-dotenv
   ```

3. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and fill in your project-specific values:

   | Variable | Description |
   |---|---|
   | `BQ_PROD_PROJECT` | GCP project ID for BigQuery queries |
   | `BQ_EXECUTABLE_PATH` | Full path to the `bq.cmd` CLI tool |
   | `BQ_DATASET` | Fully qualified BigQuery dataset (project.dataset) |
   | `CUSTOMER_LOOKUP_TABLE` | Fully qualified customer lookup table path |
   | `LLM_DEV_PROJECT` | GCP project ID for Vertex AI / Gemini |
   | `LLM_LOCATION` | Vertex AI region (e.g., `europe-west4`) |
   | `LLM_MODEL` | Gemini model name (e.g., `gemini-2.5-pro`) |
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

1. Select a **From** and **To** date range (defaults to yesterday–today)
2. Click **Get Record** to fetch a random conversation record from that range
3. Review the **User Question**, **Agent Answer**, and **Source Data**
4. Check the **LLM Review Opinion** for the automated assessment
5. Click **Yes** or **No** to record your own verdict
6. Click **Get another record** to skip and load the next record

## Project Structure

```
Magic-reviewer/
├── app.py                 # Flask backend — routes, BigQuery, LLM integration
├── css/
│   └── style.css          # UI styling and responsive breakpoints
├── teplates/
│   └── index.html         # Frontend template with review interface
├── .env.example           # Environment variable template
├── .gitignore             # Git ignore rules
└── README.md              # This file
```
