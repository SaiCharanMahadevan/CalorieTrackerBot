import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

# Local imports
from .states import ASK_LOG_MORE, AWAITING_METRIC_CHOICE
from .helpers import _get_metric_choice_keyboard

logger = logging.getLogger(__name__)

async def ask_log_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [
            InlineKeyboardButton("Log More", callback_data='log_more'),
            InlineKeyboardButton("Finish", callback_data='finish_log')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Determine how to reply (edit existing vs send new)
    reply_method = None
    if update.callback_query and update.callback_query.message:
        reply_method = update.callback_query.message.reply_text # Use the message from the callback
    elif update.message:
        reply_method = update.message.reply_text # Use the message from the update
    
    if reply_method:
        await reply_method(
            "Would you like to log more items?",
            reply_markup=reply_markup
        )
    else:
        # Fallback if neither message nor callback query message is available (should be rare)
        logger.warning("Could not determine reply method in ask_log_more")
        # Attempt to send to chat ID if possible
        if update.effective_chat:
             correct_bot = getattr(update, '_bot', None)
             if correct_bot:
                 await correct_bot.send_message(
                    update.effective_chat.id,
                    "Would you like to log more items?",
                    reply_markup=reply_markup
                 )
             else:
                 logger.error("Cannot send ask_log_more fallback: update._bot missing")
        
    return ASK_LOG_MORE

async def ask_log_more_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        # Handle cases where this might be triggered incorrectly (e.g., text message)
        logger.warning("ask_log_more_choice called without callback query.")
        # Optionally send a message back or just ignore
        if update.message:
            await update.message.reply_text("Please use the buttons.")
        return ASK_LOG_MORE # Stay in the same state or transition appropriately
        
    await query.answer()
    choice = query.data
    logger.info(f"Received ask_log_more choice: {choice}")
    if choice == 'finish_log':
        logger.info("Ending conversation from ask_log_more_choice")
        await query.edit_message_text("Logging session completed. Thanks for using the bot!")
        context.user_data.clear()
        return ConversationHandler.END
        
    # User chose 'log_more'
    logger.info("User chose to log more, displaying metric choices")
    reply_markup = _get_metric_choice_keyboard()
    await query.edit_message_text(
        "What would you like to log next?",
        reply_markup=reply_markup
    )
    logger.info("Transitioning to AWAITING_METRIC_CHOICE")
    return AWAITING_METRIC_CHOICE

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancellation from both message commands and callback queries."""
    message_text = "Logging session cancelled."
    context.user_data.clear()
    
    if update.callback_query and update.callback_query.message:
        try:
            await update.callback_query.edit_message_text(message_text)
        except Exception as e:
            logger.warning(f"Failed to edit message on cancel: {e}. Sending new message.")
            # Fallback to sending new message if edit fails
            await update.callback_query.message.reply_text(message_text)
    elif update.message:
        await update.message.reply_text(message_text)
    else:
         # Fallback if context is weird
         logger.warning("cancel_conversation called without callback_query or message.")
         if update.effective_chat:
             correct_bot = getattr(update, '_bot', None)
             if correct_bot:
                 await correct_bot.send_message(update.effective_chat.id, message_text)
             else:
                 logger.error("Cannot send cancel_conversation fallback: update._bot missing")
                 
    return ConversationHandler.END 