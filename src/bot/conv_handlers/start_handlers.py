import logging
import dateparser
from telegram import Update
from telegram.ext import ContextTypes

# Project imports
from src.services.sheets_handler import format_date_for_sheet

# Local imports
from .states import SELECTING_ACTION, AWAITING_METRIC_CHOICE
from .helpers import _get_metric_choice_keyboard

logger = logging.getLogger(__name__)

# --- /newlog Conversation Handlers ---
async def new_log_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Starting new log conversation")
    context.user_data.clear()
    await update.message.reply_text(
        "Okay, let's log some data. First, which date? (e.g., 'today', 'yesterday', 'Jul 16')"
    )
    return SELECTING_ACTION

async def received_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    date_text = update.message.text
    parsed_dt = dateparser.parse(date_text, settings={'PREFER_DATES_FROM': 'past', 'RETURN_AS_TIMEZONE_AWARE': False})
    if not parsed_dt:
        await update.message.reply_text("Sorry, I couldn't understand that date. Please try again (e.g., 'today', 'yesterday', 'Jul 16').")
        return SELECTING_ACTION
    target_date = parsed_dt.date()
    context.user_data['target_date'] = target_date
    sheet_date_str = format_date_for_sheet(target_date)
    reply_markup = _get_metric_choice_keyboard()
    await update.message.reply_text(
        f"Okay, logging for {sheet_date_str}. What would you like to log first?",
        reply_markup=reply_markup
    )
    return AWAITING_METRIC_CHOICE 