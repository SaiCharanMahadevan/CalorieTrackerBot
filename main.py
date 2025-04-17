"""Main application file for the Telegram Calorie Tracker Bot.

This file sets up the Telegram bot, defines command handlers (including conversations),
and provides the entry point for Google Cloud Functions.
"""

import logging
import json
import html
import traceback
from datetime import date, datetime

import dateparser
import functions_framework
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ApplicationBuilder,
    ConversationHandler,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode

import config
import sheets_handler
import meal_parser
import nutrition_api

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# Set higher logging level for httpx to avoid verbose INFO messages
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Bot Initialization (done globally for potential reuse) ---
bot_instance = Bot(token=config.TELEGRAM_BOT_TOKEN)

# --- Conversation States ---
(   SELECTING_ACTION,
    AWAIT_MEAL_INPUT,
    AWAIT_MEAL_CONFIRMATION,
    AWAIT_METRIC_INPUT,
) = range(4)

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the /start command is issued."""
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()}! I'm your Health Metrics Bot.\n\n"
        f"Use the /log command to add data via a single line, OR\n"
        f"Use the /newlog command to start a guided conversation.\n\n"
        f"Type /help for more details."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends help information when the /help command is issued."""
    # Define text plainly first, use a placeholder for dynamic metrics
    metric_list_str = f"`{', '.join(config.METRIC_COLUMN_MAP.keys())}`"
    help_text_template = (
        "*Commands:*\n"
        " `/start`: Show welcome message.\n"
        " `/help`: Show this help message.\n"
        " `/log [date] [metric] [value]`: Log data in a single line (see examples below).\n"
        " `/newlog`: Start a guided conversation to log metrics one by one (Recommended for meals).\n"
        " `/cancel`: Cancel the current operation (e.g., during /newlog).\n\n"

        "*Using /log:*\n"
        " `/log [optional_date] [metric_type] [value_or_description]`\n"
        " - `optional_date`: E.g., `today`, `yesterday`, `Jul 16`, `2024-07-16`. Defaults to *today*.\n"
        " - `metric_type`: `meal` or one of: METRIC_PLACEHOLDER.\n" # Placeholder
        " - `value_or_description`: Numeric value or meal description.\n\n"

        "*/log Examples:*\n"
        " `/log weight 85.5`\n"
        " `/log yesterday sleep 7.5`\n"
        " `/log Jul 15 meal 150g chicken breast and 1 cup broccoli` (Note: meal logs via /log are added directly without confirmation)\n"
        " `/log meal A quick snack`\n\n"

        "*Using /newlog (Conversational):*\n"
        " Just type `/newlog` and follow the prompts. This includes a confirmation step for meals before saving to the sheet.\n"
    )
    # Replace placeholder
    final_help_text = help_text_template.replace("METRIC_PLACEHOLDER", metric_list_str)

    # Escape the final text for MarkdownV2
    escaped_text = escape_markdown(final_help_text, version=2)

    await update.message.reply_text(escaped_text, parse_mode=ParseMode.MARKDOWN_V2)

async def log_command_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the direct /log command.
       Logs standard metrics directly.
       Logs meals directly without confirmation (use /newlog for meal confirmation).
    """
    chat_id = update.effective_chat.id
    args = context.args
    logger.info(f"Processing /log command with args: {args}")

    if not args:
        await update.message.reply_text("Please provide arguments for the /log command. Use /help for details.")
        return

    # --- Date & Metric Parsing Logic (from previous version) ---
    target_date: date = date.today()
    metric_type = ""
    value_args = []
    potential_date_str = args[0]
    metric_start_index = 0

    if len(args) > 1 and (args[1].lower() == 'meal' or args[1].lower() in config.METRIC_COLUMN_MAP):
        parsed_dt = dateparser.parse(potential_date_str, settings={'PREFER_DATES_FROM': 'past', 'STRICT_PARSING': False})
        if parsed_dt:
            target_date = parsed_dt.date()
            metric_start_index = 1
            logger.info(f"/log: Parsed date: {target_date} from '{potential_date_str}'")
        else:
            logger.info(f"/log: Could not parse '{potential_date_str}' as date. Defaulting to today.")
            metric_start_index = 0
    else:
        logger.info("/log: Second arg not metric or only one arg. Defaulting date to today.")
        metric_start_index = 0

    if len(args) <= metric_start_index:
        await update.message.reply_text("/log: Missing metric type and value.")
        return

    metric_type = args[metric_start_index].lower()
    value_args = args[metric_start_index + 1:]

    if not value_args and metric_type != 'meal':
        await update.message.reply_text(f"/log: Missing value for metric '{metric_type}'.")
        return

    value_or_description = " ".join(value_args)
    sheet_date_str = sheets_handler.format_date_for_sheet(target_date)

    # --- Direct Processing Logic ---
    try:
        if metric_type == 'meal':
            await context.bot.send_message(chat_id, f"Processing meal for {sheet_date_str} (direct log)... hang tight!")
            logger.info(f"/log: Parsing meal: {value_or_description}")
            parsed_items = meal_parser.parse_meal_text_with_gemini(value_or_description or " ")
            if not parsed_items:
                await update.message.reply_text("/log: Sorry, couldn't understand food items.")
                return

            parsed_items_str = "\n".join([f"- {i['item']} ({i['quantity_g']:.0f}g)" for i in parsed_items])
            await context.bot.send_message(chat_id, f"Parsed items:\n{parsed_items_str}\n\nLooking up nutrition...", parse_mode=ParseMode.HTML)

            nutrition_info = nutrition_api.get_nutrition_for_items(parsed_items)
            if not nutrition_info:
                await update.message.reply_text("/log: Sorry, couldn't retrieve nutritional info.")
                return

            # Log directly to Google Sheet without confirmation
            success = sheets_handler.add_nutrition(
                target_dt=target_date,
                calories=nutrition_info.get('calories', 0),
                p=nutrition_info.get('protein', 0),
                c=nutrition_info.get('carbs', 0),
                f=nutrition_info.get('fat', 0),
                fi=nutrition_info.get('fiber', 0)
            )
            if success:
                 response_text = (
                    f"✅ Meal logged directly for {sheet_date_str}!\n"
                    f"Added: {nutrition_info.get('calories', 0):.0f} Cal, " # Still show calculated Cal
                    f"{nutrition_info.get('protein', 0):.1f}g P, "
                    f"{nutrition_info.get('carbs', 0):.1f}g C, "
                    f"{nutrition_info.get('fat', 0):.1f}g F, "
                    f"{nutrition_info.get('fiber', 0):.1f}g Fi"
                 )
                 await update.message.reply_text(response_text)
            else:
                await update.message.reply_text("❌ Failed to log meal nutrition to Google Sheet.")

        elif metric_type in config.METRIC_COLUMN_MAP:
            if not value_or_description:
                await update.message.reply_text(f"/log: Missing value for metric '{metric_type}'.")
                return
            try:
                value = float(value_or_description)
            except ValueError:
                await update.message.reply_text(f"/log: Invalid numeric value '{value_or_description}' for '{metric_type}'.")
                return

            success = sheets_handler.update_metric(target_date, metric_type, value)
            if success:
                await update.message.reply_text(f"✅ Updated '{metric_type}' to '{value}' for {sheet_date_str}.")
            else:
                await update.message.reply_text(f"❌ Failed to update '{metric_type}' in Google Sheet.")
        else:
            await update.message.reply_text(f"/log: Unknown metric type '{metric_type}'. Use /help.")

    except Exception as e:
        logger.error(f"Error processing /log command: {e}", exc_info=True)
        await update.message.reply_text("😥 /log: Internal error occurred.")

# --- /newlog Conversation Handlers ---

async def new_log_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversational logging process."""
    await update.message.reply_text(
        "Okay, let's log some data. First, which date? (e.g., 'today', 'yesterday', 'Jul 16')"
    )
    return SELECTING_ACTION

async def received_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parses the date and asks for the metric type."""
    date_text = update.message.text
    parsed_dt = dateparser.parse(date_text, settings={'PREFER_DATES_FROM': 'past', 'STRICT_PARSING': False})

    if not parsed_dt:
        await update.message.reply_text("Sorry, I couldn't understand that date. Please try again (e.g., 'today', 'yesterday', 'Jul 16').")
        return SELECTING_ACTION # Stay in the same state

    context.user_data['target_date'] = parsed_dt.date()
    sheet_date_str = sheets_handler.format_date_for_sheet(context.user_data['target_date'])

    # Create buttons for metric types
    # Simple layout for buttons
    buttons_per_row = 2
    metric_buttons = [
        InlineKeyboardButton(f"Log {m.capitalize()}", callback_data=f'log_{m}')
        for m in config.METRIC_COLUMN_MAP.keys()
    ]
    keyboard = [
         [InlineKeyboardButton("Log Meal", callback_data='log_meal')]
    ]
    # Group metric buttons
    for i in range(0, len(metric_buttons), buttons_per_row):
         keyboard.append(metric_buttons[i:i + buttons_per_row])
    keyboard.append([InlineKeyboardButton("Cancel", callback_data='cancel_log')])


    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Okay, logging for {sheet_date_str}. What would you like to log?",
        reply_markup=reply_markup
    )
    return AWAIT_METRIC_INPUT

async def received_metric_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the button press choosing the metric type."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press
    choice = query.data
    context.user_data['metric_choice'] = choice # e.g., 'log_meal', 'log_weight'

    if choice == 'log_meal':
        await query.edit_message_text(text="Please describe the meal:")
        return AWAIT_MEAL_INPUT
    elif choice.startswith('log_') and choice[4:] in config.METRIC_COLUMN_MAP:
        metric_name = choice[4:]
        await query.edit_message_text(text=f"Enter the value for {metric_name.capitalize()}:")
        return AWAIT_METRIC_INPUT # Re-use state for getting value
    elif choice == 'cancel_log':
        await query.edit_message_text(text="Okay, logging cancelled.")
        context.user_data.clear()
        return ConversationHandler.END
    else:
        await query.edit_message_text(text="Invalid choice. Please start over with /newlog.")
        context.user_data.clear()
        return ConversationHandler.END

async def received_metric_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the value for a standard metric and logs it."""
    metric_name = context.user_data.get('metric_choice')[4:] # Extract from 'log_weight'
    value_text = update.message.text
    target_date = context.user_data.get('target_date')

    if not target_date or not metric_name:
         await update.message.reply_text("Error: Missing context. Please start over with /newlog.")
         context.user_data.clear()
         return ConversationHandler.END

    sheet_date_str = sheets_handler.format_date_for_sheet(target_date)

    try:
        value = float(value_text)
    except ValueError:
        await update.message.reply_text(f"Invalid numeric value '{value_text}' for {metric_name}. Please enter the value again:")
        return AWAIT_METRIC_INPUT # Ask again

    try:
        success = sheets_handler.update_metric(target_date, metric_name, value)
        if success:
            await update.message.reply_text(f"✅ Updated '{metric_name}' to '{value}' for {sheet_date_str}.")
        else:
            await update.message.reply_text(f"❌ Failed to update '{metric_name}' in the Google Sheet.")
    except Exception as e:
        logger.error(f"Error in received_metric_value for {metric_name}: {e}", exc_info=True)
        await update.message.reply_text("😥 An internal error occurred while saving.")

    context.user_data.clear()
    return ConversationHandler.END

async def received_meal_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parses the meal description and asks for confirmation."""
    meal_description = update.message.text
    target_date = context.user_data.get('target_date')

    if not target_date:
         await update.message.reply_text("Error: Missing target date. Please start over with /newlog.")
         context.user_data.clear()
         return ConversationHandler.END

    sheet_date_str = sheets_handler.format_date_for_sheet(target_date)

    # Send processing message immediately
    processing_message = await update.message.reply_text(
         f"Processing meal description for {sheet_date_str}... hang tight!",
         disable_notification=True
    )


    try:
        parsed_items = meal_parser.parse_meal_text_with_gemini(meal_description or " ")
        if not parsed_items:
            await processing_message.edit_text("Sorry, I couldn't understand the food items. Please try describing the meal again, or /cancel.")
            return AWAIT_MEAL_INPUT # Ask again

        parsed_items_str = "\n".join([f"- {i['item']} ({i['quantity_g']:.0f}g)" for i in parsed_items])
        # Construct the full message text first
        message_text = f"Parsed items:\n{parsed_items_str}\n\nLooking up nutrition..."
        # Escape the entire message for MarkdownV2
        escaped_message_text = escape_markdown(message_text, version=2)

        # Edit the message using the fully escaped text
        await processing_message.edit_text(
             escaped_message_text,
             parse_mode=ParseMode.MARKDOWN_V2
        )

        nutrition_info = nutrition_api.get_nutrition_for_items(parsed_items)
        if not nutrition_info:
             await processing_message.edit_text(
                 "Sorry, I couldn't retrieve nutritional info. Please try describing the meal again, or /cancel."
             )

             return AWAIT_MEAL_INPUT # Ask again

        # Store data for confirmation
        context.user_data['nutrition_info'] = nutrition_info

        # Prepare confirmation message - use helper for escaping
        confirmation_text_template = (
            f"Log for {sheet_date_str}:\n"
            f"Est. Add: {int(nutrition_info.get('protein', 0))}g P, "
            f"{int(nutrition_info.get('carbs', 0))}g C, "
            f"{int(nutrition_info.get('fat', 0))}g F, "
            f"{int(nutrition_info.get('fiber', 0))}g Fi\n"
            f"(Calories: {nutrition_info.get('calories', 0):.0f} - *Note: Only P/C/F/Fi are saved, Calories calculated by sheet formula*)\n\n"
            f"Do you want to save this to the sheet?"
        )
        # Escape markdown for the final text being sent
        escaped_confirmation_text = escape_markdown(confirmation_text_template, version=2)


        keyboard = [
            [InlineKeyboardButton("✅ Approve", callback_data='confirm_meal_yes'),
             InlineKeyboardButton("❌ Cancel", callback_data='confirm_meal_no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Edit the "processing" message to show the confirmation
        await processing_message.edit_text(
             escaped_confirmation_text,
             reply_markup=reply_markup,
             parse_mode=ParseMode.MARKDOWN_V2
        )

        return AWAIT_MEAL_CONFIRMATION

    except Exception as e:
        logger.error(f"Error processing meal description: {e}", exc_info=True)
        # Attempt to edit the message, otherwise send a new one if editing fails
        try:
            await processing_message.edit_text(
                 escape_markdown("😥 An internal error occurred while processing the meal. Please try again or /cancel.", version=2),
                 parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as edit_e:
             logger.error(f"Failed to edit processing message on error: {edit_e}")
             await update.message.reply_text(escape_markdown("😥 An internal error occurred while processing the meal. Please try again or /cancel.", version=2), parse_mode=ParseMode.MARKDOWN_V2)

        context.user_data.clear()
        return ConversationHandler.END


async def received_meal_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the Approve/Cancel button press for the meal."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    target_date = context.user_data.get('target_date')
    nutrition_info = context.user_data.get('nutrition_info')

    # Check if data is missing (e.g., if bot restarted during conversation)
    if not target_date or not nutrition_info:
        await query.edit_message_text("Error: Session data lost. Please start over with /newlog.")
        context.user_data.clear()
        return ConversationHandler.END

    sheet_date_str = sheets_handler.format_date_for_sheet(target_date)

    if choice == 'confirm_meal_yes':
        try:
            success = sheets_handler.add_nutrition(
                target_dt=target_date,
                calories=nutrition_info.get('calories', 0), # Pass calculated calories for logging
                p=nutrition_info.get('protein', 0),
                c=nutrition_info.get('carbs', 0),
                f=nutrition_info.get('fat', 0),
                fi=nutrition_info.get('fiber', 0)
            )
            if success:
                 # Format response text - use int() for display values P, C, F, Fi
                 response_text_template = (
                    f"✅ Meal logged successfully for {sheet_date_str}!\n"
                    f"Added: {int(nutrition_info.get('protein', 0))}g P, "
                    f"{int(nutrition_info.get('carbs', 0))}g C, "
                    f"{int(nutrition_info.get('fat', 0))}g F, "
                    f"{int(nutrition_info.get('fiber', 0))}g Fi"
                 )
                 await query.edit_message_text(escape_markdown(response_text_template, version=2), parse_mode=ParseMode.MARKDOWN_V2)

            else:
                 await query.edit_message_text(escape_markdown("❌ Failed to save meal nutrition to the Google Sheet.", version=2), parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            logger.error(f"Error saving meal nutrition after confirmation: {e}", exc_info=True)
            await query.edit_message_text(escape_markdown("😥 An internal error occurred while saving to the sheet.", version=2), parse_mode=ParseMode.MARKDOWN_V2)

    elif choice == 'confirm_meal_no':
        await query.edit_message_text(escape_markdown("Okay, meal entry cancelled.", version=2), parse_mode=ParseMode.MARKDOWN_V2)

    else: # Should not happen
        await query.edit_message_text(escape_markdown("Invalid confirmation choice.", version=2), parse_mode=ParseMode.MARKDOWN_V2)


    context.user_data.clear()
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current conversation."""
    message_text = "Operation cancelled."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(escape_markdown(message_text, version=2), parse_mode=ParseMode.MARKDOWN_V2)
    elif update.message:
        await update.message.reply_text(escape_markdown(message_text, version=2), parse_mode=ParseMode.MARKDOWN_V2)

    context.user_data.clear()
    return ConversationHandler.END


# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # Inform user (if possible)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("😥 Sorry, something went wrong processing your request.")
        except Exception as e_reply:
            logger.error(f"Failed to send error reply to user: {e_reply}")


# --- Application Setup ---
application = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

# Conversation handler for /newlog
conv_handler = ConversationHandler(
    entry_points=[CommandHandler('newlog', new_log_start)],
    states={
        SELECTING_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_date)],
        AWAIT_METRIC_INPUT: [
            CallbackQueryHandler(received_metric_choice), # Handles button presses for metric type
            MessageHandler(filters.TEXT & ~filters.COMMAND, received_metric_value) # Handles value for standard metrics
        ],
        AWAIT_MEAL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_meal_description)],
        AWAIT_MEAL_CONFIRMATION: [CallbackQueryHandler(received_meal_confirmation)], # Handles Approve/Cancel buttons
    },
    fallbacks=[CommandHandler('cancel', cancel_conversation)],
    # conversation_timeout=300 # Optional: 5 minutes
)

# Add handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("log", log_command_entry)) # Keep direct /log command
application.add_handler(conv_handler) # Add the new conversation handler

# Add error handler - make sure it's added last
application.add_error_handler(error_handler)


# --- Google Cloud Function Entry Point ---
@functions_framework.http
def telegram_webhook(request):
    """HTTP Cloud Function entry point for processing Telegram updates."""
    if request.method == "POST":
        try:
            import asyncio
            update_data = request.get_json(force=True)
            update = Update.de_json(update_data, bot_instance)
            asyncio.run(application.initialize()) # Ensures bot is ready
            asyncio.run(application.process_update(update))
            return 'ok', 200
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON from Telegram request.")
            return 'Bad Request', 400
        except Exception as e:
            logger.error(f"Error processing webhook request: {e}", exc_info=True)
            return 'ok', 200
    else:
        return 'GET request received, expecting POST from Telegram', 200


# --- Local Development Runner (Optional) ---
if __name__ == '__main__':
    logger.info("Starting bot locally via polling...")
    application.run_polling() 