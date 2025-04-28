# Telegram Health Metrics Bot

This bot allows you to log daily health metrics (like weight, sleep, steps) and meals via Telegram. It parses meal descriptions, looks up nutritional information (using USDA FoodData Central API and Google Gemini), and records the data in a designated Google Sheet.

## Features

*   **Multi-Bot Support:** Run multiple independent bot instances from a single application deployment. Each bot uses its own configuration (Google Sheet, allowed users).
*   Log various health metrics for specific dates (defaults to today).
*   Log meals using **natural language descriptions** (e.g., "150g chicken and 1 cup broccoli"), **by sending photos**, or **via voice/audio messages within the /newlog conversation**.
*   Automatically calculates estimated Calories, Protein, Carbs, Fat, and Fiber for meals using Google Gemini and USDA FoodData Central.
*   Adds meal nutrition data cumulatively to the specified date in the bot's designated Google Sheet.
*   Updates other metrics (Weight, Sleep, etc.) by overwriting the value for the specified date in the bot's designated Google Sheet.
*   Uses Google Sheets as the data backend (one sheet per configured bot).
*   Optional configuration to restrict bot usage to specific Telegram User IDs.

## Setup

1.  **Prerequisites:**
    *   Python 3.10+
    *   Google Cloud Platform (GCP) Account
    *   Telegram Account
    *   Docker and Docker Compose
    *   `jq` command-line tool (for local webhook setup in `run_local.sh`, e.g., `brew install jq` or `sudo apt-get install jq`)

2.  **Clone the Repository:**
    ```bash
    git clone <your-repo-url>
    cd <your-repo-directory>
    ```

3.  **Create Telegram Bots:**
    *   Talk to `@BotFather` on Telegram.
    *   Create one or more new bots using `/newbot`.
    *   Note down the **HTTP API Token** for each bot.

4.  **Google Cloud Setup (for Google Sheets):**
    *   Create a GCP Project (or use an existing one).
    *   **Enable APIs:** Enable the **Google Sheets API**.
    *   **Create Service Account:**
        *   Create a service account (e.g., `sheets-multi-bot-writer`).
        *   Grant it the **"Editor"** role (or more granular permissions) for the project or specific Sheets.
        *   Create and download a **JSON key file** for this service account.
    *   **Store Service Account Key:** Securely store this key file (e.g., as a secret file in Render, or accessible via path locally). **DO NOT commit it to Git.**

5.  **Google Sheets:**
    *   Create a separate Google Sheet for **each bot** you plan to configure.
    *   Ensure each sheet has the correct header rows and column order (see example `Sai Metrics - Metrics.csv`).
    *   Note down the **Sheet ID** for each sheet from its URL.
    *   **Share each Sheet:** Share *each* Google Sheet with the **client_email** found inside the service account JSON file, giving it **Editor** access.

6.  **API Keys:**
    *   **Gemini API Key:** Obtain from [Google AI Studio](https://aistudio.google.com/app/apikey).
    *   **USDA API Key:** Obtain from the [USDA FoodData Central API website](https://api.nal.usda.gov/fdc/v1/signup).

7.  **Configuration:**
    *   **Environment Variables (Required for Deployment & Local):**
        *   `GEMINI_API_KEY`: Your Gemini API Key.
        *   `USDA_API_KEY`: Your USDA API Key.
        *   Set **ONE** of the following for the Google Service Account:
            *   `GOOGLE_APPLICATION_CREDENTIALS`: **Path** to the service account JSON key file (e.g., `/etc/secrets/service-account.json` in Render, or a local path).
            *   `SERVICE_ACCOUNT_JSON`: The **content** (string) of the service account JSON key.
        *   `BOT_CONFIG_PATH` (Optional): Path to the bot configuration JSON file. Defaults to `bot_configs.json` in the project root.
    *   **`bot_configs.json` file (Required):**
        *   Create a file named `bot_configs.json` in the project root (or the path specified by `BOT_CONFIG_PATH`).
        *   This file contains a JSON array (`[]`) of configuration objects, one for each bot.
        *   **Structure:**
            ```json
            [
              {
                "bot_token": "YOUR_FIRST_BOT_TOKEN_HERE",
                "google_sheet_id": "YOUR_FIRST_BOT_SHEET_ID_HERE",
                "schema_type": "template", // Optional: "template" (default) or "legacy"
                "worksheet_name": "Sheet1", // Optional, defaults to Sheet1
                "allowed_users": [123456789] // Optional, empty list [] allows all users
              },
              {
                "bot_token": "YOUR_SECOND_BOT_TOKEN_HERE",
                "google_sheet_id": "YOUR_SECOND_BOT_SHEET_ID_HERE",
                "schema_type": "legacy" // Example: Use the legacy schema
                // worksheet_name defaults to Sheet1
                // allowed_users defaults to [] (allow all)
              }
              // Add more bot configurations as needed
            ]
            ```
        *   **`schema_type`**: Determines column mapping and the first data row (0-based index: 1 for "template", 9 for "legacy"). Use `"template"` for new sheets based on the provided template, or `"legacy"` for the original format.
        *   **Ensure `bot_configs.json` is added to your `.gitignore` file!**
    *   **Local `.env` file (For Development ONLY):**
        *   You can place the environment variables (`GEMINI_API_KEY`, `USDA_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS` or `SERVICE_ACCOUNT_JSON`, `BOT_CONFIG_PATH`) in a `.env` file for local development convenience. The `run_local.sh` script also requires `NGROK_AUTH_TOKEN` in `.env`.
        *   **Example `.env`:**
            ```dotenv
            GEMINI_API_KEY=YOUR_GEMINI_API_KEY_PLACEHOLDER
            USDA_API_KEY=YOUR_USDA_API_KEY_PLACEHOLDER
            GOOGLE_APPLICATION_CREDENTIALS=./path/to/your/local-service-account.json # Or use SERVICE_ACCOUNT_JSON="{...}"
            BOT_CONFIG_PATH=./bot_configs.json # Optional, defaults to ./bot_configs.json
            NGROK_AUTH_TOKEN=YOUR_NGROK_TOKEN_FROM_NGROK_DASHBOARD
            ```
        *   **Ensure `.env` is added to your `.gitignore` file!**

## Deployment

This application is designed to be deployed as a Docker container using Render.

### Render Deployment

Render deploys automatically based on commits to the linked Git repository branch (e.g., `main`).

1.  **Prerequisites:**
    *   Code pushed to a Git provider (GitHub, GitLab, Bitbucket).
    *   Render account created and connected to the Git provider.
    *   A "Web Service" created on Render, linked to the correct repository and branch.
2.  **Configuration (Render Dashboard):**
    *   **Runtime:** Set to `Docker`.
    *   **Health Check Path:** Set to `/health`.
    *   **Environment Variables & Secrets:** Configure the following in the service's "Environment" section:
        *   Regular Variables: `GEMINI_API_KEY`, `USDA_API_KEY`, `PYTHON_VERSION` (e.g., `3.10`), `PORT` (e.g., `8080`).
        *   Secret Files:
            *   Add a secret file named `service-account.json` containing the Google Service Account JSON key content.
            *   Add another secret file named `bot_configs.json` containing the JSON array of your bot configurations.
        *   Add Environment Variables:
            *   `GOOGLE_APPLICATION_CREDENTIALS` with the value `/etc/secrets/service-account.json`.
            *   `BOT_CONFIG_PATH` with the value `/etc/secrets/bot_configs.json`.
3.  **Deployment Workflow:**
    *   Commit and push changes to the linked branch.
    *   Render automatically builds and deploys.
4.  **Initial Webhook Setup (Per Bot):** After the *first* successful deployment, manually set the Telegram webhook **for each bot** to point to its specific Render service URL path:
    ```bash
    # For Bot 1:
    curl -F "url=https://<your-render-service-url>/webhook/<YOUR_FIRST_BOT_TOKEN>" \
         https://api.telegram.org/bot<YOUR_FIRST_BOT_TOKEN>/setWebhook

    # For Bot 2:
    curl -F "url=https://<your-render-service-url>/webhook/<YOUR_SECOND_BOT_TOKEN>" \
         https://api.telegram.org/bot<YOUR_SECOND_BOT_TOKEN>/setWebhook
    
    # Repeat for all configured bots...
    ```
    *(This only needs to be done once per bot, not for subsequent code deployments)*.

## Usage

Talk to any of your configured bots on Telegram:

*   `/start`: Get a welcome message.
*   `/help`: See command usage details.
*   `/log [date] [metric] [value]`: Log data (see `/help` for examples). Note: Does not support audio logging.
*   `/newlog`: Start a guided conversation to log multiple items. Supports **text, photo, and voice/audio input** for meals.
*   `/daily_summary`: Show today's calories, macros (Protein, Carbs, Fat, Fiber), and steps.
*   `/weekly_summary`: Show average sleep, weight, steps, and calories for the current week (starting from the most recent Sunday).
*   `/cancel`: Cancel the current conversation if it's stuck or you want to start over.

Data will be logged to the Google Sheet associated with the specific bot you are interacting with.

## Local Development

Use the provided `run_local.sh` script:

```bash
# Run locally
./scripts/run_local.sh

# Run locally with live code reloading
./scripts/run_local.sh --watch
```

This script handles:
1.  Checking for `NGROK_AUTH_TOKEN` in `.env` (required).
2.  Starting the `bot` and `ngrok` services via `docker compose`.
3.  Waiting for the ngrok tunnel to be ready.
4.  **Automatically setting the webhook for each bot listed in `bot_configs.json`** to point to the correct ngrok URL (e.g., `https://<random-id>.ngrok.io/webhook/<BOT_TOKEN>`). This requires `jq` to be installed locally.
5.  Providing live reload in `--watch` mode.

**Important:** Ensure your `.env` file and `bot_configs.json` are correctly set up locally before running the script.

**Logs & Control:**
*   Follow logs: `docker compose logs -f bot`
*   Stop: `docker compose down`
*   Ngrok UI: `http://localhost:4040`

## File Structure

```
.
├── src/                    # Source code directory
│   ├── app.py             # FastAPI application entry point & webhook handlers
│   ├── bot/               # Bot logic and handlers
│   │   ├── bot_logic.py   # Main PTB Application setup, conversation handler structure
│   │   ├── direct_commands.py # Handlers for direct commands (/start, /help, /log)
│   │   ├── conversation_handlers.py # Handlers for /newlog conversation states
│   │   ├── helpers.py     # Helper functions used by bot handlers
│   │   └── __init__.py
│   ├── config/            # Configuration loading and definitions
│   │   ├── config_loader.py # Loads bot configurations from file/env
│   │   ├── config.py      # Defines dataclasses for config, constants
│   │   └── __init__.py
│   ├── services/          # Core services (external APIs, parsing)
│   │   ├── sheets_handler.py # Interacts with Google Sheets API
│   │   ├── meal_parser.py # Parses meal text/images using Gemini
│   │   ├── audio_processor.py # Transcribes voice/audio messages using Gemini
│   │   ├── nutrition_api.py # Fetches nutrition data from USDA API
│   │   ├── ai_models.py   # Initializes AI models (e.g., Gemini)
│   │   └── __init__.py
│   ├── utils.py           # Shared utility functions
│   └── __init__.py
├── scripts/               # Utility scripts
│   └── run_local.sh       # Local development runner & multi-webhook setup
├── tests/                 # Unit/integration tests (Placeholder)
├── .github/               # GitHub Actions workflows (e.g., CI/CD)
├── .env                   # Local environment variables (DO NOT COMMIT!)
├── .gitignore             # Git ignore rules
├── .dockerignore          # Docker ignore rules
├── .python-version        # Specifies Python version (e.g., for pyenv)
├── bot_configs.json       # Bot configurations (DO NOT COMMIT!)
├── docker-compose.yml     # Docker Compose configuration for local dev
├── Dockerfile             # Docker configuration for deployment
├── requirements.txt       # Python dependencies
├── README.md              # This file
├── service-account-key.json # Google Service Account Key (DO NOT COMMIT!)
├── setup_webhook.sh       # Manual script to set webhook (e.g., for Render initial setup)
```

## Key Components

*   **`src/app.py`:** FastAPI app, handles dynamic `/webhook/{bot_token}` requests, initializes the correct `Bot` instance per request, routes updates to PTB.
*   **`src/bot/` directory:** Contains all logic related to the Telegram bot interaction using `python-telegram-bot`.
    *   **`bot_logic.py`:** Sets up the main `telegram.ext.Application` and registers all command, message, and conversation handlers.
    *   **`direct_commands.py`:** Implements handlers for simple, one-off commands like `/start`, `/help`, and `/log`.
    *   **`conversation_handlers.py`:** Implements the state machine and handlers for the multi-step `/newlog` conversation.
    *   **`helpers.py`:** Contains utility functions specifically for the bot handlers (e.g., getting bot config, error handling).
*   **`src/config/config_loader.py`:** Loads shared config and bot-specific configs from `bot_configs.json` and environment variables.
*   **`src/services/` directory:** Contains modules responsible for interacting with external APIs and performing core data processing.
    *   **`sheets_handler.py`:** Interacts with Google Sheets API.
    *   **`meal_parser.py`:** Parses meal text/images using Gemini.
    *   **`audio_processor.py`:** Transcribes voice/audio messages using Gemini. 
    *   **`nutrition_api.py`:** Fetches nutrition data from USDA API.
    *   **`ai_models.py`:** Initializes AI models (e.g., Gemini).
*   **`src/utils.py`:** Contains general utility functions used across the application.
*   **`bot_configs.json`:** Defines configurations for multiple bots (tokens, sheet IDs, allowed users, schema_type).
*   **`scripts/run_local.sh`:** Sets up local dev environment and configures webhooks for all bots defined in `bot_configs.json` using ngrok.
*   **`setup_webhook.sh`:** Manual script primarily for setting webhooks in a deployed environment like Render where `run_local.sh` isn't applicable.
*   **(Other components as previously described - Docker config etc.)**

## Troubleshooting

*   **"Chat not found" errors:** Ensure the correct bot token is being used (check logs vs `bot_configs.json`), the bot hasn't been blocked by the user, and the webhook is set correctly for that specific bot token (`/webhook/<TOKEN>`).
*   **Config not found:** Verify `BOT_CONFIG_PATH` environment variable (if used) points to the correct location, or that `bot_configs.json` exists at the project root/container path. Check file permissions.
*   **Webhook errors:** Check the output of `./scripts/run_local.sh` or your manual `curl` commands when setting webhooks. Ensure the ngrok/Render URL is correct and reachable.
*   **Docker errors:** Check `docker compose logs` for build or runtime errors.

# Calorie Tracker Bot Templates

This directory contains template files for setting up your Google Sheet to work with the Calorie Tracker Bot:

1. `docs/template_sheet_schema.md` - Detailed documentation of the required Google Sheets structure, including:
   - Column specifications and data types
   - Setup instructions
   - Configuration steps
   - Tips and troubleshooting

2. `docs/template_sheet.csv` - A CSV file that you can import into Google Sheets to quickly create a properly formatted sheet:
   - Contains all required column headers
   - Includes an example row showing correct data formats
   - Can be imported directly into Google Sheets

## Quick Start

1. Create a new Google Sheet
2. Go to File > Import > Upload > Select `docs/template_sheet.csv`
3. Choose "Replace current sheet" when importing
4. Name your worksheet "Daily Tracking" (or update the config to match your chosen name)
5. Share the sheet with your bot's service account email
6. Copy the Google Sheet ID from the URL
7. Update your bot's configuration with the Sheet ID

## Detailed Setup

For complete setup instructions and schema details, please refer to `docs/template_sheet_schema.md`.