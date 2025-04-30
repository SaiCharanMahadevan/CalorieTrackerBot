#!/bin/bash

set -e # Exit on error
# set -o pipefail # Exit on pipe failures

# --- PIDs for background processes ---
NGROK_PID=""
UVICORN_PID=""

# --- Cleanup function ---
cleanup() {
    echo "" # Newline
    print_status "Cleaning up background processes..."
    if [ -n "$UVICORN_PID" ]; then
        echo -n "  Stopping Uvicorn (PID: $UVICORN_PID)... "
        # Send SIGTERM first, then SIGKILL if it doesn't stop
        kill "$UVICORN_PID" 2>/dev/null || true 
        sleep 1
        kill -9 "$UVICORN_PID" 2>/dev/null || true
        echo "Stopped."
    fi
    if [ -n "$NGROK_PID" ]; then
        echo -n "  Stopping ngrok (PID: $NGROK_PID)... "
        kill "$NGROK_PID" 2>/dev/null || true
        sleep 1
        kill -9 "$NGROK_PID" 2>/dev/null || true
        echo "Stopped."
    fi
    # Clean up log files if they exist
    rm -f ngrok.log uvicorn.log
    print_status "Cleanup complete."
    exit 0 # Ensure clean exit after trap
}

# --- Trap SIGINT and EXIT signals ---
trap cleanup SIGINT EXIT

# --- Colors for output ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# --- Helper functions for printing ---
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# --- Dependency Checks ---
print_status "Checking dependencies..."
MISSING_DEPS=()
command -v python3 >/dev/null 2>&1 || MISSING_DEPS+=("python3")
command -v pip >/dev/null 2>&1 || MISSING_DEPS+=("pip")
command -v ngrok >/dev/null 2>&1 || MISSING_DEPS+=("ngrok (install from https://ngrok.com/download)")
command -v jq >/dev/null 2>&1 || MISSING_DEPS+=("jq (e.g., 'brew install jq' or 'sudo apt-get install jq')")

if [ ${#MISSING_DEPS[@]} -ne 0 ]; then
    print_error "Missing required dependencies:"
    for dep in "${MISSING_DEPS[@]}"; do
        echo -e "  - ${RED}${dep}${NC}"
    done
    exit 1
fi
print_status "All dependencies found."

# --- Environment Setup ---
# Load .env file if it exists
if [ -f ".env" ]; then
    print_status "Loading environment variables from .env file..."
    # Use 'export' with 'set -a' to make variables available to subprocesses
    set -a 
    source .env
    set +a
else
    print_warning ".env file not found. Ensure required environment variables (e.g., GOOGLE_APPLICATION_CREDENTIALS, GEMINI_API_KEY) are set manually."
fi

# Check for NGROK_AUTH_TOKEN (optional but recommended)
if [ -z "$NGROK_AUTH_TOKEN" ]; then
    print_warning "NGROK_AUTH_TOKEN is not set in the environment or .env file. Ngrok tunnel might be temporary or fail if not configured globally."
else
    # --- Add ngrok authtoken configuration --- <<< ADDED
    print_status "Configuring ngrok with provided authtoken..."
    # Use --log=stderr to avoid polluting stdout if needed, but simple echo is fine here
    ngrok config add-authtoken "$NGROK_AUTH_TOKEN" 
    print_status "Ngrok authtoken configured."
    # -----------------------------------------
fi

# --- Python Dependencies ---
if [ -f "requirements.txt" ]; then
    print_status "Ensuring pip is up-to-date..."
    # Upgrade pip first, bypassing SSL verification if needed, to handle potential SSL issues
    python3 -m pip install --upgrade pip --trusted-host pypi.org --trusted-host files.pythonhosted.org
    
    print_status "Installing/checking Python dependencies from requirements.txt..."
    pip install -r requirements.txt
else
    print_warning "requirements.txt not found. Skipping Python dependency installation."
fi

# --- Kill Conflicting Processes ---
print_status "Checking for conflicting processes..."
# Kill processes listening on ngrok's API port (4040) or the app's port (8000)
lsof -ti :4040 | xargs kill -9 2>/dev/null || true
lsof -ti :8000 | xargs kill -9 2>/dev/null || true
sleep 1 # Give a moment for ports to free up

# --- Start ngrok ---
print_status "Starting ngrok to expose port 8000..."
# Start ngrok in the background, redirecting output to a log file
# Now that the token is configured, this command should succeed.
ngrok http 8000 --log=stdout > ngrok.log &
NGROK_PID=$!
print_status "ngrok started in background (PID: $NGROK_PID). Logs: ngrok.log"

# --- Start FastAPI Application ---
print_status "Starting FastAPI application with Uvicorn..."
# Start uvicorn in the background, redirecting output to a log file
# Assuming src/app.py uses Python's logging, uvicorn should respect it.
uvicorn src.app:app --host 0.0.0.0 --port 8000 > uvicorn.log 2>&1 &
UVICORN_PID=$!
print_status "Uvicorn started in background (PID: $UVICORN_PID). Logs: uvicorn.log"

# --- Wait for Services ---
# Wait for ngrok URL
NGROK_URL=""
MAX_RETRIES=15 # Increased retries
RETRY_COUNT=0
print_status "Waiting for ngrok tunnel..."
while [ -z "$NGROK_URL" ] && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    sleep 3 # Wait between retries
    # Attempt to get HTTPS URL from ngrok's local API
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels | jq -r '.tunnels[] | select(.proto=="https") | .public_url' 2>/dev/null)
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ -z "$NGROK_URL" ]; then
         echo -e "  Retrying ngrok status check (${RETRY_COUNT}/${MAX_RETRIES})..."
    fi
done

if [ -z "$NGROK_URL" ]; then
    print_error "Could not get ngrok public URL after $MAX_RETRIES attempts."
    print_error "Check ngrok status (http://127.0.0.1:4040) and logs (ngrok.log)."
    exit 1 # Trigger cleanup via EXIT trap
fi
print_status "Got ngrok URL: $NGROK_URL"

# Wait for FastAPI app health check
APP_HEALTHY=false
MAX_RETRIES=10
RETRY_COUNT=0
print_status "Waiting for FastAPI application health check..."
while [ "$APP_HEALTHY" = false ] && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    sleep 2
    # Check the /health endpoint
    if curl -s --fail http://127.0.0.1:8000/health > /dev/null; then
        APP_HEALTHY=true
        print_status "FastAPI application is healthy."
    else
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo -e "  Retrying app health check (${RETRY_COUNT}/${MAX_RETRIES})..."
    fi
done

if [ "$APP_HEALTHY" = false ]; then
    print_error "FastAPI application did not become healthy after $MAX_RETRIES attempts."
    print_error "Check application logs (uvicorn.log)."
    exit 1 # Trigger cleanup via EXIT trap
fi

# --- Set Webhooks ---
print_status "Setting up webhooks for configured bots..."
CONFIG_FILE="bot_configs.json"
if [ ! -f "$CONFIG_FILE" ]; then
    print_error "Bot configuration file not found at $CONFIG_FILE."
    print_warning "Skipping automatic webhook setup."
else
    # Use jq to extract tokens into an array (handles spaces etc.)
    BOT_TOKENS=()
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Add non-empty lines to the array
        if [[ -n "$line" ]]; then
            BOT_TOKENS+=("$line")
        fi
    done < <(jq -r '.[] | .bot_token? // empty' "$CONFIG_FILE")

    if [ ${#BOT_TOKENS[@]} -eq 0 ]; then
         print_warning "No valid bot tokens found in $CONFIG_FILE."
    else
         print_status "Found ${#BOT_TOKENS[@]} bot token(s) in config."
         # Ensure no double slashes if NGROK_URL ends with /
         NGROK_BASE=$(echo "$NGROK_URL" | sed 's:/*$::') 

         for TOKEN in "${BOT_TOKENS[@]}"; do
             # Basic check if token seems valid
             if [[ -n "$TOKEN" && "$TOKEN" != "null" ]]; then
                 # Construct per-bot webhook URL
                 WEBHOOK_TARGET_URL="${NGROK_BASE}/webhook/${TOKEN}"
                 echo -n "  Setting webhook for token ${TOKEN:0:8}... to ${WEBHOOK_TARGET_URL}: "
                 # Use curl to set the webhook
                 API_URL="https://api.telegram.org/bot${TOKEN}/setWebhook"
                 RESPONSE=$(curl -s -F "url=${WEBHOOK_TARGET_URL}" "${API_URL}")

                 # Check response
                 if echo "$RESPONSE" | jq -e '.ok == true' > /dev/null; then
                     echo -e "${GREEN}OK${NC}"
                 else
                     ERROR_DESC=$(echo "$RESPONSE" | jq -r '.description // "Unknown error"')
                     echo -e "${RED}FAILED${NC} (${ERROR_DESC})"
                 fi
             else
                print_warning "  Skipping empty or null token entry from config file."
             fi
         done
         print_status "Webhook setup process complete."
    fi
fi

# --- Success Message ---
echo ""
print_status "Local environment is running!"
echo -e "  ${YELLOW}App URL (local):${NC} http://localhost:8000"
echo -e "  ${YELLOW}Ngrok URL (public):${NC} ${NGROK_URL}"
echo ""
echo -e "${GREEN}Logs:${NC}"
echo -e "  • Uvicorn App: ${YELLOW}tail -f uvicorn.log${NC}"
echo -e "  • Ngrok Tunnel: ${YELLOW}tail -f ngrok.log${NC}"
echo -e "  • Ngrok UI:    ${YELLOW}http://localhost:4040${NC}"
echo ""
print_warning "Press Ctrl+C to stop the application and ngrok."
echo ""

# --- Keep script running ---
# Wait indefinitely for background processes; cleanup trap handles exit
wait
