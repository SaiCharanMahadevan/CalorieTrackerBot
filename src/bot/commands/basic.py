"""Handlers for basic informational commands like /start and /help."""

import logging
import html
import telegram # Keep telegram (used for errors/classes)
from telegram import Update, Bot
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# Project imports
from src.config.config import LOGGING_CHOICES_MAP

logger = logging.getLogger(__name__)


# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the /start command is issued."""
    user = update.effective_user
    # Using update.message.reply_html implicitly uses the correct bot instance
    await update.message.reply_html(
        f"Hi {user.mention_html()}! I'm your Health Metrics Bot.\n\n"
        f"Use the /log command to add data via a single line, OR\n"
        f"Use the /newlog command to start a guided conversation to log multiple items for a date.\n\n"
        f"You can now log meals by sending photos! Just use /log meal with a photo attached, or send a photo during the /newlog conversation.\n\n"
        f"Type /help for more details."
    )

async def help_command(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    """Sends help information when the /help command is issued."""
    # Escape the dynamic part using HTML escaping
    metric_list_html = html.escape(f"`{', '.join(LOGGING_CHOICES_MAP.keys())}`")

    # Use HTML tags for formatting
    help_text = (
        f"<b>Commands:</b> 📜\n"
        f" `/start`: Show welcome message.\n"
        f" `/help`: Show this help message.\n"
        f" `/log [metric] [value]`: Log data in a single line (see examples below).\n"
        f" `/newlog`: Start a guided conversation to log multiple items for a date (Recommended for meals).\n"
        f" `/daily_summary`: Show today's calories, macros (P/C/F/Fi), and steps.\n"
        f" `/weekly_summary`: Show average sleep, weight, steps, and calories for the current week (Sun-Today).\n"
        f" `/cancel`: Cancel the current logging operation (e.g., during `/newlog`).\n\n"
        f"<b>Using /log:</b> ⌨️\n"
        f" `/log [metric_type] [value_or_description]`\n"
        f" - `metric_type`: <code>meal</code> or one of: {metric_list_html}.\n" # Use code tags for metrics
        f" - `value_or_description`: Numeric value(s) or meal description.\n\n"
        f"<b>/log Examples:</b> ✨\n"
        f" `/log weight 85.5` - Log weight in kg/lbs\n"
        f" `/log weight 85.5 0930` - Log weight with time (HHMM format)\n"
        f" `/log sleep 7.5 8` - Log sleep hours (7.5) and quality rating (8)\n"
        f" `/log steps 10000` - Log step count\n"
        f" `/log wellness 8 7 8 9` - Log energy, mood, satiety, digestion ratings\n"
        f" `/log cardio 30min run` - Log cardio activity\n"
        f" `/log training legs day` - Log training activity\n"
        f" `/log water 8` - Log water intake\n"
        f" `/log meal 150g chicken breast and 1 cup broccoli` - Quick meal log (no confirmation)\n"
        f" `/log meal` (with a photo attached) - Log a meal by sending a photo\n\n"
        f"<b>Using /newlog (Recommended for Meals):</b> 💬\n"
        f" Just type `/newlog` and follow the prompts. Benefits:\n"
        f" - Choose the date for your entry\n"
        f" - Review parsed items before logging\n"
        f" - Edit nutrition values if needed\n"
        f" - Log multiple items for the same date\n"
        f" - Supports <b>text, photo, and voice/audio input</b> for meals!\n\n"
        f"<b>Image Upload Feature:</b> 📷\n"
        f" You can log meals by sending photos:\n"
        f" 1. During the `/newlog` conversation, when prompted\n"
        f" 2. Using `/log meal` with a photo attached\n"
        f" The bot will analyze the image, identify food items, estimate portions, and calculate nutrition.\n\n"
        f"<b>Audio/Voice Feature:</b> 🎤\n"
        f" You can describe your meal using a voice message during the `/newlog` conversation when prompted for meal details.\n\n"
        f"<b>Important Notes:</b> 📌\n"
        f" - All `/log` commands default to today's date\n"
        f" - To log for a different date, use `/newlog`\n"
        f" - For meals, `/newlog` is recommended as it provides confirmation and editing options\n"
        f" - Some metrics require multiple values (e.g., sleep needs hours and quality rating)"
    )
    
    chat_id = update.message.chat.id if update.message and update.message.chat else None
    
    # --- Get the ACTUAL bot object (_bot) ---
    correct_bot = getattr(update, '_bot', None) # Use internal attribute
    bot_token_snippet = correct_bot.token[:6] + "..." if correct_bot and correct_bot.token else "Unknown"
    # -----------------------------------------

    logger.info(f"Attempting to send help message to chat_id: {chat_id} using ACTUAL bot token: {bot_token_snippet}")
    if not chat_id:
        logger.error("Could not determine chat_id in help_command.")
        return 
    if not correct_bot: # Check if _bot itself is valid
        logger.error(f"Could not access update._bot in help_command for update {update.update_id}.")
        return 
        
    # --- Use update._bot explicitly ---
    try:
        # Use the bot instance associated with the specific update (internal attribute)
        await correct_bot.send_message( # <<< Use correct_bot (which is update._bot)
            chat_id=chat_id, 
            text=help_text, # Use the correctly formatted text
            parse_mode=ParseMode.HTML # <-- Change parse mode to HTML
        )
        logger.info(f"Successfully sent help message to chat_id: {chat_id} using token {bot_token_snippet}")
    except telegram.error.BadRequest as e:
        logger.error(f"BadRequest sending help message via update._bot ({bot_token_snippet}) to chat_id {chat_id}: {e}", exc_info=True)
        if "Chat not found" in str(e):
             logger.error(f"Telegram API reports 'Chat not found' for chat_id {chat_id} with token {bot_token_snippet}. Check token validity, bot permissions, and chat status.")
    except Exception as e:
        logger.error(f"Error sending help message via update._bot ({bot_token_snippet}) to chat_id {chat_id}: {e}", exc_info=True)
    # -----------------------------------------------------------------


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles any command that doesn't match the known commands."""
    await update.message.reply_text(
        "Sorry, I didn't understand that command. Type /help to see available commands."
    ) 