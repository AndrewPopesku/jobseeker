# Jobseeker

An AI-powered job application assistant that searches for jobs on Indeed and LinkedIn, generates tailored LaTeX CVs compiled to PDF, uploads them to Google Drive, and logs each application to a Google Sheets tracker.

Built on [Google ADK](https://github.com/google/adk-python) with Gemini, delivered via a Telegram bot.

---

## Features

- **Job search** — scrapes Indeed and LinkedIn based on your query and location
- **Tailored CV generation** — rewrites your CV in LaTeX to match the job description keywords
- **PDF compilation** — compiles LaTeX to PDF via a dedicated compiler microservice
- **Google Drive upload** — uploads each CV PDF to a configured Drive folder
- **Application tracker** — logs every application (job link, company, position, CV link) to Google Sheets
- **Versioned CVs** — every generated/updated CV is saved as a named artifact version
- **Telegram interface** — interact with the agent through a private Telegram bot

---

## Architecture

```
Telegram Bot
    └── root_agent (LlmAgent, Gemini)
            ├── job_search_agent     — Indeed + LinkedIn scraping
            └── cv_creator_agent     — LaTeX CV generation, Drive upload, Sheets logging
                        │
                        └── compiler service  (FastAPI + pdflatex, runs in Docker)
```

The **compiler service** is a separate container that exposes an HTTP endpoint to compile LaTeX source to PDF. The main bot calls it at `COMPILER_SERVICE_URL`.

---

## Prerequisites

- Python 3.13+
- Docker & Docker Compose
- A Google Cloud project with:
  - Google Drive API enabled
  - Google Sheets API enabled
  - OAuth 2.0 credentials (`credentials.json`)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- A Gemini API key

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/AndrewPopesku/jobseeker.git
cd jobseeker
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in all values:

| Variable | Description |
|---|---|
| `GOOGLE_API_KEY` | Gemini API key |
| `LANGSMITH_API_KEY` | LangSmith API key (for tracing) |
| `LANGSMITH_PROJECT` | LangSmith project name |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_USER_ID` | Your numeric Telegram user ID |
| `GOOGLE_DRIVE_FOLDER_ID` | ID of the Drive folder for CV uploads |
| `GOOGLE_SHEETS_ID` | Spreadsheet ID for the application tracker |
| `GOOGLE_SHEETS_GID` | Sheet tab GID |
| `COMPILER_SERVICE_URL` | URL of the compiler container (set automatically in Docker Compose) |

### 3. Add Google credentials

Place your OAuth 2.0 credentials file at:

```
jobseeker/credentials.json
```

On first run, the bot will open a browser for OAuth consent and save the token to `jobseeker/token.json`.

### 4. Prepare your personal data

Edit `me.txt` with your personal information (name, contact details, experience, skills, etc.). The agent reads this file when generating your CV.

---

## Running

### With Docker Compose (recommended)

```bash
docker-compose up --build
```

This starts two containers:
- `compiler` — LaTeX compilation service on port 8081
- `bot` — Telegram bot

### Locally (without Docker)

```bash
# Install dependencies
pip install -e .

# Start the compiler service separately
cd compiler && uvicorn main:app --port 8080 &

# Set the compiler URL
export COMPILER_SERVICE_URL=http://localhost:8080

# Run the bot
python telegram_bot.py
```

---

## Usage

Start a conversation with your Telegram bot. Example prompts:

```
Find Python backend jobs in Warsaw
```
```
Search for remote ML engineer positions
```
```
Create a CV for the first job
```
```
Update my CV — add Docker to the skills section
```

The agent will guide you through the workflow: search → select a job → generate a tailored CV → receive a Drive link and tracker row.

---

## Deploy to Google Cloud Run

Terraform configuration is provided in the `terraform/` directory.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Fill in terraform.tfvars with your GCP project details
terraform init
terraform apply
```

---

## Project Structure

```
jobseeker/
├── jobseeker/
│   ├── agent.py              # Root agent definition
│   ├── job_search_agent.py   # Job search sub-agent
│   ├── cv_creator_agent.py   # CV creation sub-agent
│   ├── tools.py              # Indeed + LinkedIn scrapers
│   ├── cv_tools.py           # LaTeX generation + compiler client
│   ├── google_tools.py       # Drive upload + Sheets logging
│   └── credentials.json      # (not committed) Google OAuth credentials
├── compiler/
│   ├── main.py               # FastAPI app — compiles LaTeX to PDF
│   └── Dockerfile
├── terraform/                # GCP Cloud Run deployment
├── telegram_bot.py           # Telegram bot entry point
├── docker-compose.yml
├── pyproject.toml
├── .env.example
└── me.txt                    # Your personal data for CV generation
```

---

## License

MIT
