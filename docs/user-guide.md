# Magic Reviewer User Guide

## Overview

Magic Reviewer is a compliance review tool for evaluating AI-generated responses in HSBC Business Banking. It pulls conversation records from BigQuery, runs them through an LLM (Gemini) for automated analysis, and presents the results for human validation.

## Getting Started

1. Open `http://localhost:5000` in your browser.
2. The date range defaults to yesterday through today. Adjust if needed.
3. Click **Get Record** to load a random unreviewed record.

## Review Workflow

### Step 1: Read the Conversation

- **User Question**: What the Relationship Manager asked.
- **Agent Answer**: What the AI agent responded.

### Step 2: Check the Source Data

- The right panel shows the raw customer JSON data the agent had access to.
- Use the **search box** above the source data to find specific fields (e.g., search for "credit_limit" to jump to that field).
- When the LLM review completes, relevant fields are highlighted:
  - **Green highlight**: The agent correctly cited this field.
  - **Yellow highlight**: The agent may have misused or incorrectly cited this field.

### Step 3: Review the LLM Opinion

- The LLM Review Opinion card shows the automated assessment.
- A **green border** means the LLM found the answer correct.
- A **red border** means the LLM found issues (wrong facts, wrong fields, safety/brand violations).
- Read the reasoning to understand what the LLM flagged.

### Step 4: Cast Your Vote

- Click **Yes (Y)** if you agree the agent's answer is correct and grounded in source data.
- Click **No (N)** if you find issues. A text box appears for you to describe the problem.
- Click **Skip (S)** to move on without voting.

After voting Yes or No, the next record loads automatically after a brief confirmation.

### Review Counter

The counter in the top-right corner shows how many records you have reviewed this session. It resets when you refresh the page.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Y   | Vote Yes |
| N   | Vote No (opens reason input) |
| S   | Skip and load next |

Shortcuts only work when you are not typing in a text field.

## What Gets Saved

Each review saves the following to BigQuery:

- Session ID and turn position (identifies the conversation record)
- Customer ID, user email, response source, lookup status (record metadata)
- Your vote (YES, NO, or Skip)
- Your reason (if you voted No)
- The LLM's verdict (is_correct, safety violation, brand violation, reasoning)
- Timestamp

The BI team uses this data for reporting and dashboard analysis.

## Critical Field Rules

Pay attention to these commonly confused fields:

| Term | Correct Field | Table |
|------|--------------|-------|
| "credit limit" | `credit_limit_amount_gbp` | dim_account |
| "BIB limit" / "payment limit" | `bib_payment_limit_amount_gbp` | dim_customer |
| "CAGR" | `cagr_percentage` (cite directly, never recalculate) | dim_customer |

If the agent uses the wrong field name for any of these, the answer is incorrect.

## Troubleshooting

- **"BQ query returned 0 rows"**: No unreviewed records exist in the selected date range. Try a wider range or check if all records have already been reviewed.
- **"LLM review failed"**: The Gemini API call failed. Check network connectivity and proxy configuration.
- **"Save failed"**: The BQ insert failed. Check that the review table exists and the schema matches.
- **Buttons not responding**: Wait for the current operation to complete. Buttons are disabled during fetch/save operations.
