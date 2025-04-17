import logging
from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, Request, Response, HTTPException
from telegram import Update, Bot
from telegram.ext import Application

# --- Import from utils ---
from src.utils import sanitize_token

from src.config.config_loader import get_config, AppConfig
from src.bot.bot_logic import create_telegram_application

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    # Ensure logs are in a format that Cloud Logging can parse
    datefmt='%Y-%m-%dT%H:%M:%S.%fZ'
)

# Set higher logging level for noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

# Get the root logger and set its level
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Create a logger for our application
logger = logging.getLogger(__name__)

# --- Global Variables ---
# Will hold the initialized PTB application and config
telegram_app: Application | None = None
# app_settings is no longer strictly needed globally if config is singleton
# app_settings: AppConfig | None = None

# --- FastAPI Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown events for the FastAPI app."""
    global telegram_app # Keep telegram_app global
    logger.info("FastAPI application starting up...")
    try:
        # Load configuration (ensure singleton is loaded)
        logger.info("Loading application configuration via singleton...")
        app_settings = get_config() # This loads the singleton instance
        
        # --- Get a default token for ApplicationBuilder ---
        if not app_settings.bot_configs:
            logger.critical("No bot configurations loaded. Application cannot start.")
            raise RuntimeError("No bot configurations found in bot_configs.json")
            
        # Use the token from the first configuration entry as the default
        default_bot_token = app_settings.bot_configs[0].get("bot_token")
        if not default_bot_token:
             logger.critical("The first entry in bot_configs.json is missing a 'bot_token'.")
             raise RuntimeError("Invalid first bot configuration entry.")
        logger.info(f"Loaded {len(app_settings.bot_configs)} bot configurations. Using token starting with {default_bot_token[:6]}... as default for PTB Application build.")
        # -------------------------------------------------

        # Create and initialize the Telegram application (passing the default token)
        logger.info("Creating and initializing Telegram application...")
        telegram_app = create_telegram_application(default_token=default_bot_token)
        await telegram_app.initialize()
        logger.info("Telegram application initialized.")

        logger.info("FastAPI startup complete. Telegram App is ready.")
        yield # Application runs here

    except Exception as e:
        logger.critical(f"Application startup failed: {e}", exc_info=True)
        raise RuntimeError(f"Application startup failed: {e}") from e
    finally:
        # --- Shutdown Logic ---
        logger.info("FastAPI application shutting down...")
        if telegram_app:
            logger.info("Stopping Telegram application...")
            await telegram_app.shutdown()
            logger.info("Telegram application shutdown complete.")
        logger.info("FastAPI shutdown complete.")

# --- FastAPI App Instance ---
app = FastAPI(
    title="Telegram Multi-Bot Health Metrics",
    description="A FastAPI application handling webhooks for multiple Telegram bots via dynamic paths",
    version="1.1.0", # Increment version
    lifespan=lifespan
)

# --- Webhook Endpoint ---
# @app.post("/") # Listen at the root path <-- This was the version before multi-token path
# async def handle_webhook(request: Request):
#     """Handles incoming Telegram updates and passes them to the PTB application."""
#     if not telegram_app:
#         logger.error("Telegram application not initialized during request handling.")
#         raise HTTPException(status_code=503, detail="Bot service not available")
# 
#     try:
#         data = await request.json()
#         update = Update.de_json(data, telegram_app.bot) 
#         logger.debug(f"Received update {update.update_id}")
#         await telegram_app.process_update(update)
#         return Response(status_code=200)
#     except json.JSONDecodeError:
#         logger.error("Failed to decode JSON from webhook request body.")
#         raise HTTPException(status_code=400, detail="Invalid JSON payload")
#     except Exception as e:
#         logger.error(f"Error processing update in webhook handler: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail="Error processing update")

# --- Restore original simpler root endpoint (optional - can be removed if not needed) ---
# This will likely only work correctly if the DEFAULT bot (first in config)
# has its webhook set to the root URL.
@app.post("/")
async def handle_root_webhook(request: Request):
    """Handles webhook POST requests at the root path (e.g., for a default bot)."""
    if not telegram_app:
        logger.error("Root webhook: Telegram application not initialized.")
        raise HTTPException(status_code=503, detail="Bot service not available")

    try:
        data = await request.json()
        # Deserialize using the application's default bot
        update = Update.de_json(data, telegram_app.bot)
        logger.info(f"Root webhook received update {update.update_id} (using default bot context)")
        
        # Optional: Add validation here if you want to restrict the root endpoint
        # to ONLY the default bot token.
        # default_token = get_config().bot_configs[0].get("bot_token")
        # if not update._bot or update._bot.token != default_token:
        #    logger.warning("Root webhook received update for non-default bot. Ignoring.")
        #    return Response(status_code=403)
            
        await telegram_app.process_update(update)
        return Response(status_code=200)
    except json.JSONDecodeError:
        logger.error("Root webhook: Failed to decode JSON.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.error(f"Root webhook: Error processing update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error processing update")
# ----------------------------------------------------------------------------------

# --- NEW Dynamic Webhook Endpoint --- 
@app.post("/webhook/{bot_token}")
async def handle_bot_webhook(request: Request, bot_token: str):
    """Handles incoming Telegram updates for a specific bot token via dynamic path."""
    if not telegram_app:
        logger.error(f"Webhook/{bot_token[:6]}...: Telegram application not initialized.")
        raise HTTPException(status_code=503, detail="Bot service not available")

    logger.debug(f"Webhook received for token snippet: {bot_token[:6]}...")
    
    # --- Validate token and get config ---
    app_config = get_config()
    sanitized_path_token = sanitize_token(bot_token) 
    bot_config = app_config.get_bot_config_by_token(sanitized_path_token)

    if not bot_config:
        logger.warning(f"Webhook received for unknown/unconfigured bot token: {bot_token[:6]}...")
        return Response(status_code=404) # Not Found
        
    try:
        data = await request.json()
        
        # --- Instantiate Bot with token from path & Deserialize ---
        try:
            # Use the validated token from path
            # Important: Ensure the token passed to Bot() is the original one from the path,
            # not necessarily the sanitized one used for lookup, as Telegram needs the exact token.
            actual_bot = Bot(token=bot_token)
            
            # --- Initialize the Bot instance ---
            logger.debug(f"Initializing bot instance for {bot_token[:6]}...")
            await actual_bot.initialize()
            logger.debug(f"Bot instance for {bot_token[:6]}... initialized (Username: {actual_bot.username})")
            # -----------------------------------
            
            update = Update.de_json(data, actual_bot) # Deserialize WITH the correct bot context
            logger.debug(f"Deserialized update {update.update_id} using bot {bot_token[:6]}...")
        except Exception as de_json_error:
             logger.error(f"Failed to instantiate, initialize, or deserialize update for token {bot_token[:6]}...: {de_json_error}", exc_info=True)
             raise HTTPException(status_code=500, detail="Update processing error (init/deserialize)")
        # -------------------------------------------------------

        # --- Check allowed users --- 
        allowed_users = bot_config.get("allowed_users", [])
        if allowed_users: # Only check if the list is not empty
            if not update.effective_user or update.effective_user.id not in allowed_users:
                logger.warning(f"User {update.effective_user.id if update.effective_user else 'Unknown'} is not authorized for bot token {bot_token[:6]}... Update {update.update_id} ignored.")
                return Response(status_code=403) # Forbidden
        # --------------------------

        # Pass the update (now associated with the correct bot) to the PTB application
        logger.info(f"Processing update {update.update_id} for bot token {bot_token[:6]}... (Sheet: {bot_config['google_sheet_id']})")
        await telegram_app.process_update(update)
        return Response(status_code=200)

    except json.JSONDecodeError:
        logger.error(f"Webhook/{bot_token[:6]}...: Failed to decode JSON.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.error(f"Webhook/{bot_token[:6]}...: Error processing update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error processing update")

# Health check endpoint (optional but good practice)
@app.get("/health")
async def health_check():
    """Health check endpoint that verifies the application is initialized."""
    if not telegram_app:
        raise HTTPException(status_code=503, detail="Application not fully initialized")
    
    return {
        "status": "healthy",
        "initialized": True
    }

# --- Main execution for local testing (using uvicorn) ---
# This block is typically NOT run in production container deployments,
# where uvicorn is started via the Docker CMD or Procfile.
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Uvicorn server for local development...")
    # You would run this file using: uvicorn app:app --reload --port 8000
    # The following line is mostly for IDEs that run the file directly
    uvicorn.run(app, host="0.0.0.0", port=8000) 