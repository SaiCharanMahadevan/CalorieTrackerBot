import logging

from telegram import Update # Keep for potential future use or type hinting clarity
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes, # Keep for error_handler in helpers.py
    # ApplicationBuilder, # Unused
    ConversationHandler,
    CallbackQueryHandler,
)

# --- Import handlers from new modules ---
from .direct_commands import start, help_command, log_command_entry, unknown_command
from .conversation_handlers import (
    # Import states directly
    SELECTING_ACTION, AWAITING_METRIC_CHOICE, AWAIT_MEAL_INPUT, AWAIT_MEAL_CONFIRMATION, 
    AWAIT_METRIC_INPUT, ASK_LOG_MORE, AWAIT_MACRO_EDIT, 
    # Import handlers
    new_log_start, received_date, received_metric_choice, received_metric_value,
    received_meal_description, received_meal_confirmation, received_macro_edit, 
    ask_log_more_choice, cancel_conversation
)
from .helpers import error_handler
# -------------------------------------

logger = logging.getLogger(__name__)


def create_telegram_application(default_token: str) -> Application:
    """Creates and configures the Telegram application using a default token for initialization."""
    if not default_token:
         logger.critical("create_telegram_application called without a default_token.")
         raise ValueError("A default bot token is required to build the Telegram Application.")
         
    application = Application.builder().token(default_token).build()
    logger.info(f"Built PTB Application using default token: {default_token[:6]}...")

    # --- Use IMPORTED handlers and states for ConversationHandler --- 
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('newlog', new_log_start)], # Imported
        states={
            SELECTING_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_date) # Imported
            ],
            AWAITING_METRIC_CHOICE: [
                CallbackQueryHandler(received_metric_choice) # Imported
            ],
            AWAIT_MEAL_INPUT: [
                MessageHandler(filters.TEXT | filters.PHOTO, received_meal_description) # Imported
            ],
            AWAIT_MEAL_CONFIRMATION: [
                CallbackQueryHandler(received_meal_confirmation, pattern='^confirm_meal_'), # Imported
                CallbackQueryHandler(received_meal_confirmation, pattern='^edit_macros$') # Imported
            ],
            AWAIT_METRIC_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_metric_value) # Imported
            ],
            ASK_LOG_MORE: [
                CallbackQueryHandler(ask_log_more_choice, pattern='^(log_more|finish_log)$') # Imported
            ],
            AWAIT_MACRO_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_macro_edit) # Imported
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation), # Imported
            CallbackQueryHandler(cancel_conversation, pattern='^cancel_log$') # Imported
        ],
        allow_reentry=True
    )
    application.add_handler(conv_handler)

    # --- Use IMPORTED handlers for direct commands ---
    application.add_handler(CommandHandler("start", start)) # Imported
    application.add_handler(CommandHandler("help", help_command)) # Imported
    
    # --- Handlers for /log command --- 
    # Handler for /log in standard text messages
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'^/log(?:@\w+)?(?:\s|$)'), 
        log_command_entry
    ))
    # Handler for any photo (will check for /log meal caption inside)
    application.add_handler(MessageHandler(
        filters.PHOTO, 
        log_command_entry
    ))
    # ----------------------------------

    # --- Use IMPORTED handler for unknown commands ---
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command)) # Imported

    # Add error handler (now imported)
    application.add_error_handler(error_handler) # <<< Uses imported handler

    return application 