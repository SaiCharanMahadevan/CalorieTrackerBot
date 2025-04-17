import logging
from typing import Optional, Dict, Any

from telegram import Update # Needed for type hinting
from telegram.ext import ContextTypes

from src.config.config_loader import get_config # Needed to access config

logger = logging.getLogger(__name__)

def _get_current_sheet_config(update: Update) -> Optional[Dict[str, Any]]:
    """Retrieves the sheet configuration for the bot associated with the update."""
    # --- Use internal _bot attribute ---
    the_bot = getattr(update, '_bot', None) # Safely access internal attribute
    if not the_bot or not the_bot.token:
        logger.warning("Cannot get sheet config: Update._bot or its token is missing.")
        return None
    bot_token = the_bot.token
    # -----------------------------------

    config = get_config() # Get singleton config instance
    bot_config = config.get_bot_config_by_token(bot_token)
    
    if not bot_config:
        logger.warning(f"No configuration found for bot token starting with: {bot_token[:6]}... Update {update.update_id if update else 'N/A'} ignored.")
        return None
        
    # Basic check for required keys (should be guaranteed by loader, but belts and suspenders)
    if "google_sheet_id" not in bot_config or "worksheet_name" not in bot_config:
         logger.error(f"Incomplete config found for bot token {bot_token[:6]}... : {bot_config}")
         return None
         
    # --- Check Allowed Users Here ---
    allowed_users = bot_config.get("allowed_users", [])
    if allowed_users: # Only check if the list is not empty
        if not update.effective_user or update.effective_user.id not in allowed_users:
            logger.warning(f"User {update.effective_user.id if update.effective_user else 'Unknown'} is not authorized for bot token {bot_token[:6]}... Update {update.update_id if update else 'N/A'} ignored.")
            # We can't easily send a message from here, handlers should check the return value
            return None # Indicate failure due to authorization
    # ----------------------------
            
    return bot_config 

# --- Error Handler --- 
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs errors caused by updates."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    # Check if update is available and has attributes needed for reply
    if isinstance(update, Update) and update.effective_message:
        error_message = str(context.error)
        reply_text = "Sorry, an error occurred while processing your request. Please try again later."
        if "Bad Request" in error_message:
            logger.warning("Telegram Bad Request error - possibly formatting or API issue.")
            reply_text = "Sorry, there was an error communicating with Telegram. Please try again."
        # Add more specific error checks if needed
        try:
             # Use update.effective_message.reply_text - implicitly uses correct bot
             await update.effective_message.reply_text(reply_text)
        except Exception as reply_err:
             logger.error(f"Failed to send error reply message: {reply_err}")
    elif context and context.error:
        # Log cases where update might not be available or not have effective_message
        logger.error(f"Error handler invoked without a usable Update object. Error: {context.error}")
    else:
        logger.error("Generic error handler invoked with insufficient context.") 