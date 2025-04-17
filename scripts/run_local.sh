#!/bin/bash

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print status messages
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker first."
    exit 1
fi

# Make sure the NGROK_AUTH_TOKEN is set in .env
if ! grep -q "NGROK_AUTH_TOKEN=" .env || ! grep -q "NGROK_AUTH_TOKEN=.*[a-zA-Z0-9]" .env; then
    NGROK_TOKEN=$(cat ~/.ngrok2/ngrok.yml 2>/dev/null | grep authtoken | cut -d' ' -f2 || cat ~/.config/ngrok/ngrok.yml 2>/dev/null | grep authtoken | cut -d' ' -f2)
    
    if [ -n "$NGROK_TOKEN" ]; then
        # Update the .env file with the found token
        if grep -q "NGROK_AUTH_TOKEN=" .env; then
            # Replace existing line
            sed -i '' "s|NGROK_AUTH_TOKEN=.*|NGROK_AUTH_TOKEN=$NGROK_TOKEN|" .env
        else
            # Add new line
            echo "NGROK_AUTH_TOKEN=$NGROK_TOKEN" >> .env
        fi
        print_status "Updated .env file with ngrok auth token"
    else
        print_error "No ngrok auth token found. Please add it manually to .env"
        exit 1
    fi
fi

# Clean up any existing containers
print_status "Cleaning up existing containers..."
docker compose down --remove-orphans > /dev/null 2>&1 || true

# Build and start services with development profile
print_status "Starting services in development mode..."
COMPOSE_PROFILES=development docker compose up -d --build

# Give a moment for services to start and show initial logs
print_status "Starting services (this may take a few seconds)..."
sleep 3
docker compose logs --tail=20 bot

# Run the webhook setup script
# print_status "Setting up webhook..."
# ./setup_webhook.sh # <-- REMOVED OLD SCRIPT CALL

# --- New Webhook Setup Logic --- <<< ADDED
print_status "Setting up webhooks for configured bots..."

# 1. Check for jq (JSON processor)
if ! command -v jq &> /dev/null; then
    print_error "'jq' command not found. Please install jq (e.g., 'brew install jq' or 'apt-get install jq') to parse bot_configs.json."
    print_warning "Skipping automatic webhook setup."
else
    # 2. Wait for ngrok and get public URL
    NGROK_URL=""
    MAX_RETRIES=10
    RETRY_COUNT=0
    print_status "Waiting for ngrok tunnel..."
    while [ -z "$NGROK_URL" ] && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        sleep 5 # Wait longer between retries
        # Attempt to get HTTPS URL first, fallback to HTTP if needed (though HTTPS is required by Telegram)
        NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | jq -r '.tunnels[] | select(.proto=="https") | .public_url' 2>/dev/null)
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ -z "$NGROK_URL" ]; then
             echo -e "  Retrying ngrok status check (${RETRY_COUNT}/${MAX_RETRIES})..."
        fi
    done

    if [ -z "$NGROK_URL" ]; then
        print_error "Could not get ngrok public URL after $MAX_RETRIES attempts. Make sure ngrok service is running correctly in docker-compose."
        print_warning "Skipping automatic webhook setup."
    else
        print_status "Got ngrok URL: $NGROK_URL"

        # 3. Parse bot_configs.json and set webhooks
        CONFIG_FILE="bot_configs.json" # <-- CORRECT path relative to execution dir (project root)
        if [ ! -f "$CONFIG_FILE" ]; then
            print_error "Bot configuration file not found at $CONFIG_FILE."
            print_warning "Skipping automatic webhook setup."
        else
            # Use jq to extract tokens into an array (handles spaces in filenames etc.)
            # mapfile -t BOT_TOKENS < <(jq -r '.[] | .bot_token? // empty' "$CONFIG_FILE") # <-- Original mapfile command
            
            # --- Use more portable while read loop instead of mapfile --- <<< FIX
            BOT_TOKENS=()
            while IFS= read -r line || [[ -n "$line" ]]; do
                # Add non-empty lines to the array
                if [[ -n "$line" ]]; then
                    BOT_TOKENS+=("$line")
                fi
            done < <(jq -r '.[] | .bot_token? // empty' "$CONFIG_FILE")
            # -----------------------------------------------------------

            if [ ${#BOT_TOKENS[@]} -eq 0 ]; then
                 print_warning "No valid bot tokens found in $CONFIG_FILE."
            else
                 print_status "Found ${#BOT_TOKENS[@]} bot token(s) in config."
                 # WEBHOOK_TARGET_URL="${NGROK_URL}/" # Old root URL

                 for TOKEN in "${BOT_TOKENS[@]}"; do
                     # Basic check if token seems valid (avoids empty strings)
                     if [[ -n "$TOKEN" && "$TOKEN" != "null" ]]; then
                         # --- Construct per-bot webhook URL --- <<< MODIFIED
                         # Ensure no double slashes if NGROK_URL ends with /
                         NGROK_BASE=$(echo "$NGROK_URL" | sed 's:/*$::') 
                         WEBHOOK_TARGET_URL="${NGROK_BASE}/webhook/${TOKEN}"
                         # ---------------------------------------
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
    fi
fi
# --- End New Webhook Setup Logic ---

print_status "Local development environment is running!"
echo
echo -e "${GREEN}Available Commands:${NC}"
echo "• View logs:           ${YELLOW}docker compose logs -f${NC}"
echo "• Shell into bot:      ${YELLOW}docker compose exec bot /bin/bash${NC}"
echo "• Stop services:       ${YELLOW}docker compose down${NC}"
echo "• Rebuild services:    ${YELLOW}docker compose up -d --build${NC}"
echo "• View ngrok UI:       ${YELLOW}http://localhost:4040${NC}"
echo
print_status "Your bot is ready for development! 🚀"
print_warning "If you encounter any issues, check the logs with: docker compose logs bot"

# Start watching for changes (optional)
if [[ "$*" == *"--watch"* ]]; then
    print_status "Starting watch mode for live reload..."
    docker compose watch
fi 