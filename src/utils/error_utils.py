import logging
import html
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# Basic error logging (can be expanded)
def log_error(message: str, update: Update | None = None, context: ContextTypes.DEFAULT_TYPE | None = None, exc_info=False):
    """Logs an error message, optionally including user/chat info and exception details."""
    log_message = f"ERROR: {message}"
    if update and update.effective_user:
        log_message += f" | User ID: {update.effective_user.id}"
    if update and update.effective_chat:
        log_message += f" | Chat ID: {update.effective_chat.id}"
    
    # Use logger.error which handles exc_info automatically if True
    logger.error(log_message, exc_info=exc_info)


async def send_error_message(update: Update, context: ContextTypes.DEFAULT_TYPE, error_text: str):
    """Sends a standardized error message reply to the user."""
    logger.info(f"Sending error message to chat {update.effective_chat.id}: {error_text}")
    try:
        # Escape the error text for safety, though specific formatters might be better
        safe_error_text = f"❌ An error occurred: {html.escape(error_text)}"
        
        if update.callback_query:
             # If triggered by a button, try editing the message
             await update.callback_query.edit_message_text(safe_error_text)
        elif update.message:
             # If triggered by a message, reply to it
             await update.message.reply_text(safe_error_text)
        else:
             # Fallback if no message/query context (less common)
             await context.bot.send_message(chat_id=update.effective_chat.id, text=safe_error_text)
             
    except Exception as e:
        logger.error(f"Failed to send error message '{error_text}' to chat {update.effective_chat.id}: {e}", exc_info=True)

# Potential future additions:
# - format_error_html(...) - for more complex HTML formatted errors 