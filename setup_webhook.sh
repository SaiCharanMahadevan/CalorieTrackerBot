#!/bin/bash

# Load the Telegram Bot Token from .env file
TELEGRAM_BOT_TOKEN=$(grep TELEGRAM_BOT_TOKEN .env | cut -d '=' -f2)

# Wait for ngrok to start
echo "Waiting for ngrok to start..."
sleep 10

# Get the public URL from ngrok API
NGROK_PUBLIC_URL=$(curl -s http://localhost:4040/api/tunnels | grep -o '"public_url":"https://[^"]*' | cut -d '"' -f4)

if [ -z "$NGROK_PUBLIC_URL" ]; then
  echo "Error: Could not get ngrok public URL. Make sure ngrok is running and the ngrok web interface is accessible at http://localhost:4040"
  exit 1
fi

echo "Setting Telegram webhook to: $NGROK_PUBLIC_URL"

# Set the webhook
RESPONSE=$(curl -s -F "url=$NGROK_PUBLIC_URL" https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook)

echo "Response from Telegram:"
echo $RESPONSE

if [[ $RESPONSE == *"\"ok\":true"* ]]; then
  echo "✅ Webhook set successfully!"
else
  echo "❌ Failed to set webhook. Check the response for details."
fi 