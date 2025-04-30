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
from .commands import (
    start, help_command, log_command_entry, unknown_command, 
    daily_summary_command, weekly_summary_command
)
# Import from the new conv_handlers package via its __init__.py
from .conv_handlers import (
    SELECTING_ACTION, AWAITING_METRIC_CHOICE, AWAIT_MEAL_INPUT, AWAIT_MEAL_CONFIRMATION, 
    AWAIT_METRIC_INPUT, ASK_LOG_MORE, AWAIT_MACRO_EDIT, AWAIT_ITEM_QUANTITY_EDIT,
    new_log_start, received_date, received_metric_choice, received_metric_value,
    received_meal_description, received_item_quantity_edit, received_meal_confirmation, 
    received_macro_edit, ask_log_more_choice, cancel_conversation
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
        entry_points=[CommandHandler('newlog', new_log_start)], # Use imported handler
        states={
            SELECTING_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_date)], # Use imported state & handler
            AWAITING_METRIC_CHOICE: [
                CallbackQueryHandler(received_metric_choice), # Use imported handler
                CallbackQueryHandler(cancel_conversation, pattern='^cancel_log$') # Handle cancel here too
            ],
            AWAIT_METRIC_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_metric_value)], # Use imported state & handler
            AWAIT_MEAL_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_meal_description), # Use imported state & handler
                MessageHandler(filters.PHOTO, received_meal_description), # Handle photo
                MessageHandler(filters.VOICE | filters.AUDIO, received_meal_description) # Handle audio/voice
            ],
            AWAIT_ITEM_QUANTITY_EDIT: [ 
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_item_quantity_edit)
            ],
            AWAIT_MEAL_CONFIRMATION: [
                CallbackQueryHandler(received_meal_confirmation), # Use imported handler
                 CallbackQueryHandler(cancel_conversation, pattern='^confirm_meal_no$') # Added explicit cancel route
            ],
            AWAIT_MACRO_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_macro_edit)], # Use imported state & handler
            ASK_LOG_MORE: [CallbackQueryHandler(ask_log_more_choice)] # Use imported state & handler
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation), # Use imported handler
            # Removed CallbackQueryHandler for cancel_log here as it's handled in AWAITING_METRIC_CHOICE
            # Keep a general message fallback?
            # MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_state_message) # Optional: catch unhandled text
        ],
        allow_reentry=True
    )
    application.add_handler(conv_handler)

    # --- Use IMPORTED handlers for direct commands ---
    application.add_handler(CommandHandler("start", start)) # Imported from .commands
    application.add_handler(CommandHandler("help", help_command)) # Imported from .commands
    
    # --- Register New Summary Commands ---
    application.add_handler(CommandHandler("daily_summary", daily_summary_command)) # Imported from .commands
    application.add_handler(CommandHandler("weekly_summary", weekly_summary_command)) # Imported from .commands
    # -----------------------------------
    
    # --- Handlers for /log command --- 
    # Handler for /log in standard text messages
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'^/log(?:@\w+)?(?:\s|$)'), 
        log_command_entry # Imported from .commands
    ))
    # Handler for any photo (will check for /log meal caption inside)
    application.add_handler(MessageHandler(
        filters.PHOTO, 
        log_command_entry # Imported from .commands
    ))
    # ----------------------------------

    # --- Use IMPORTED handler for unknown commands ---
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command)) # Imported from .commands

    # Add error handler (now imported)
    application.add_error_handler(error_handler) # <<< Uses imported handler

    return application