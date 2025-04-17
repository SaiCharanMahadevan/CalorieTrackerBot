# Telegram Health Metrics Bot

This bot allows you to log daily health metrics (like weight, sleep, steps) and meals via Telegram. It parses meal descriptions, looks up nutritional information (using USDA FoodData Central API and Google Gemini), and records the data in a designated Google Sheet.

## Features

*   Log various health metrics for specific dates (defaults to today).
*   Log meals using natural language descriptions (e.g., "150g chicken and 1 cup broccoli").
*   Automatically calculates estimated Calories, Protein, Carbs, Fat, and Fiber for meals.
*   Adds meal nutrition data cumulatively to the specified date in the Google Sheet.
*   Updates other metrics (Weight, Sleep, etc.) by overwriting the value for the specified date.
*   Uses Google Sheets as the data backend.
*   Designed for deployment as a Google Cloud Function.

## Setup

1.  **Prerequisites:**
    *   Python 3.10+
    *   Google Cloud Platform (GCP) Account
    *   Telegram Account

2.  **Clone the Repository:**
    ```bash
    git clone <your-repo-url>
    cd <your-repo-directory>
    ```

3.  **Create a Telegram Bot:**
    *   Talk to `@BotFather` on Telegram.
    *   Create a new bot using `/newbot`.
    *   Note down the **HTTP API Token** provided.

4.  **Google Cloud Setup:**
    *   Create a GCP Project (or use an existing one).
    *   **Enable APIs:** Enable the **Google Sheets API** and **Cloud Functions API** in your GCP project.
    *   **Create Service Account:**
        *   Go to "IAM & Admin" > "Service Accounts".
        *   Click "Create Service Account".
        *   Give it a name (e.g., `sheets-bot-writer`).
        *   Grant it the **"Editor"** role (or more granular permissions like "Google Sheets API Editor" if preferred) for this project, or at least for the specific Google Sheet.
        *   Click "Done".
        *   Find the created service account, go to the "Keys" tab.
        *   Click "Add Key" > "Create new key".
        *   Choose **JSON** and click "Create". A JSON key file will be downloaded.
    *   **Store Service Account Key:** Securely store this downloaded JSON file. **DO NOT commit it to Git.** For Cloud Functions, the recommended way is using [Secret Manager](https://cloud.google.com/secret-manager).

5.  **Google Sheet:**
    *   Create a Google Sheet based on the schema shown in the example `Sai Metrics - Metrics.csv` (pay attention to header rows and column order).
    *   Note down the **Sheet ID** from its URL (`docs.google.com/spreadsheets/d/SHEET_ID/edit`).
    *   **Share the Sheet:** Share the Google Sheet with the **client_email** found inside the downloaded service account JSON file, giving it **Editor** access.

6.  **API Keys:**
    *   **Gemini API Key:** Obtain an API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
    *   **USDA API Key:** Obtain an API key from the [USDA FoodData Central API website](https://api.nal.usda.gov/fdc/v1/signup).

7.  **Configuration:**
    *   **Option A (Environment Variables - Recommended for GCP):** Set the following environment variables in your Cloud Function deployment environment:
        *   `TELEGRAM_BOT_TOKEN`: Your Telegram Bot Token.
        *   `GOOGLE_SHEET_ID`: Your Google Sheet ID.
        *   `WORKSHEET_NAME`: The name of the worksheet (e.g., `Sheet1`).
        *   `SERVICE_ACCOUNT_FILE`: The *path* where the service account JSON key will be accessible within the Cloud Function environment (if mounting from Secret Manager, this might be `/secrets/service-account/key.json`, for example).
        *   `GEMINI_API_KEY`: Your Gemini API Key.
        *   `USDA_API_KEY`: Your USDA API Key.
    *   **Option B (Local `.env` file - For Development ONLY):**
        *   Create a file named `.env` in the project root.
        *   Add the keys like this (replace placeholders):
            ```dotenv
            TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN_PLACEHOLDER
            GOOGLE_SHEET_ID=YOUR_GOOGLE_SHEET_ID_PLACEHOLDER
            WORKSHEET_NAME=Sheet1
            SERVICE_ACCOUNT_FILE=path/to/your/service_account.json # Use relative or absolute path
            GEMINI_API_KEY=YOUR_GEMINI_API_KEY_PLACEHOLDER
            USDA_API_KEY=YOUR_USDA_API_KEY_PLACEHOLDER
            ```
        *   Uncomment the `python-dotenv` lines in `config.py`.
        *   **Ensure `.env` is added to your `.gitignore` file!**
    *   **Option C (Directly in `config.py` - NOT Recommended for Secrets):** Edit `config.py` directly. Least secure method.

8.  **Install Dependencies:**
    *   **Using `uv` (Recommended & Faster):**
        ```bash
        # Install uv if you haven't already: https://github.com/astral-sh/uv
        # Create and activate virtual environment
        uv venv
        source .venv/bin/activate # On macOS/Linux. Use `.venv\Scripts\activate` on Windows.

        # Install dependencies
        uv pip install -r requirements.txt
        ```
    *   **Using standard `venv`/`pip`:**
        ```bash
        python -m venv venv
        source venv/bin/activate # On Windows use `venv\Scripts\activate`
        pip install -r requirements.txt
        ```

## Deployment (Google Cloud Functions)

1.  **Deploy using `gcloud` CLI:**

    ```bash
    gcloud functions deploy telegram-health-metrics-webhook \
        --gen2 \
        --runtime python311 `# Or python310, python312 etc.` \
        --region YOUR_GCP_REGION `# e.g., us-central1` \
        --source . \
        --entry-point telegram_webhook \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars TELEGRAM_BOT_TOKEN=YOUR_TOKEN,GOOGLE_SHEET_ID=YOUR_SHEET_ID,WORKSHEET_NAME=Sheet1,SERVICE_ACCOUNT_FILE=path/to/key.json,GEMINI_API_KEY=YOUR_GEMINI_KEY,USDA_API_KEY=YOUR_USDA_KEY
        # Add --set-secrets for managing secrets via Secret Manager (recommended)
        # e.g., --set-secrets=TELEGRAM_BOT_TOKEN=your-secret-name:latest, ...
    ```

    *   Replace placeholders (`YOUR_GCP_REGION`, `YOUR_TOKEN`, etc.) with your actual values.
    *   Adjust the `runtime` if necessary.
    *   Modify `--set-env-vars` or use `--set-secrets` based on how you configured secrets.
    *   Note the **HTTPS Trigger URL** provided after successful deployment.

2.  **Set Telegram Webhook:**
    *   Replace `YOUR_BOT_TOKEN` and `YOUR_FUNCTION_URL` in the command below.
    *   Run this command in your terminal (or use a tool like Postman):

        ```bash
        curl -F "url=YOUR_FUNCTION_URL" https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook
        ```
    *   You should get a response like `{"ok":true,"result":true,"description":"Webhook was set"}`.

## Usage

Talk to your bot on Telegram:

*   `/start`: Get a welcome message.
*   `/help`: See command usage details.
*   `/log [date] [metric] [value]`: Log data (see `/help` for examples).

## Local Development

1.  Ensure you have set up configuration (e.g., using a `.env` file).
2.  Make sure the Service Account JSON file path in your config is correct.
3.  Activate your virtual environment (`source .venv/bin/activate` or `source venv/bin/activate`).
4.  Uncomment the `if __name__ == '__main__':` block at the bottom of `main.py`.
5.  Run the bot locally:

    ```bash
    python main.py
    ```
    The bot will start polling Telegram for updates (this does not use the webhook).
 