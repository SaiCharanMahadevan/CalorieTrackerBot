"""Handlers for direct, non-conversational commands."""

import logging
from datetime import date
import dateparser

import telegram # Keep telegram (used for errors/classes)
from telegram import Update, Bot
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

# Project imports
from src.config.config import LOGGING_CHOICES_MAP # Keep this one
from src.services.sheets_handler import update_metrics, add_nutrition, format_date_for_sheet
from src.services.meal_parser import parse_meal_text_with_gemini, parse_meal_image_with_gemini
from src.services.nutrition_api import get_nutrition_for_items
# Need the helper to get config for the current bot
from .helpers import _get_current_sheet_config

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
    metric_list_str = f"`{', '.join(LOGGING_CHOICES_MAP.keys())}`"
    help_text_template = (
        "*Commands:*\n"
        " `/start`: Show welcome message.\n"
        " `/help`: Show this help message.\n"
        " `/log [metric] [value]`: Log data in a single line (see examples below).\n"
        " `/newlog`: Start a guided conversation to log multiple items for a date (Recommended for meals).\n"
        " `/cancel`: Cancel the current logging operation (e.g., during `/newlog`).\n\n"
        "*Using /log:*\n"
        " `/log [metric_type] [value_or_description]`\n"
        " - `metric_type`: `meal` or one of: METRIC_PLACEHOLDER.\n"
        " - `value_or_description`: Numeric value(s) or meal description.\n\n"
        "*/log Examples:*\n"
        " `/log weight 85.5` - Log weight in kg/lbs\n"
        " `/log weight 85.5 0930` - Log weight with time (HHMM format)\n"
        " `/log sleep 7.5 8` - Log sleep hours (7.5) and quality rating (8)\n"
        " `/log steps 10000` - Log step count\n"
        " `/log wellness 8 7 8 9` - Log energy, mood, satiety, digestion ratings\n"
        " `/log cardio 30min run` - Log cardio activity\n"
        " `/log training legs day` - Log training activity\n"
        " `/log water 8` - Log water intake\n"
        " `/log meal 150g chicken breast and 1 cup broccoli` - Quick meal log (no confirmation)\n"
        " `/log meal` (with a photo attached) - Log a meal by sending a photo\n\n"
        "*Using /newlog (Recommended for Meals):*\n"
        " Just type `/newlog` and follow the prompts. Benefits:\n"
        " - Choose the date for your entry\n"
        " - Review parsed items before logging\n"
        " - Edit nutrition values if needed\n"
        " - Log multiple items for the same date\n"
        " You can also send a photo of your meal during the process.\n\n"
        "*Image Upload Feature:*\n"
        " You can log meals by sending photos:\n"
        " 1. During the `/newlog` conversation, when prompted\n"
        " 2. Using `/log meal` with a photo attached\n"
        " The bot will analyze the image, identify food items, estimate portions, and calculate nutrition.\n\n"
        "*Important Notes:*\n"
        " - All `/log` commands default to today's date\n"
        " - To log for a different date, use `/newlog`\n"
        " - For meals, `/newlog` is recommended as it provides confirmation and editing options\n"
        " - Some metrics require multiple values (e.g., sleep needs hours and quality rating)"
    )
    final_help_text = help_text_template.replace("METRIC_PLACEHOLDER", metric_list_str)
    escaped_text = escape_markdown(final_help_text, version=2)

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
            text=escaped_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        logger.info(f"Successfully sent help message to chat_id: {chat_id} using token {bot_token_snippet}")
    except telegram.error.BadRequest as e:
        logger.error(f"BadRequest sending help message via update._bot ({bot_token_snippet}) to chat_id {chat_id}: {e}", exc_info=True)
        if "Chat not found" in str(e):
             logger.error(f"Telegram API reports 'Chat not found' for chat_id {chat_id} with token {bot_token_snippet}. Check token validity, bot permissions, and chat status.")
    except Exception as e:
        logger.error(f"Error sending help message via update._bot ({bot_token_snippet}) to chat_id {chat_id}: {e}", exc_info=True)
    # -----------------------------------------------------------------

# --- Helper: Photo Log Handling ---
async def _handle_photo_log(update: Update, context: ContextTypes.DEFAULT_TYPE, sheet_config: dict, correct_bot: Bot):
    """Handles logging when a photo is received (expecting /log meal caption)."""
    chat_id = update.effective_chat.id
    caption = update.message.caption
    bot_token_snippet = correct_bot.token[:6] + "..." if correct_bot.token else "Unknown"

    # Validate caption
    if not caption or not caption.lower().startswith("/log meal"):
        logger.info(f"_handle_photo_log: Received photo without valid '/log meal' caption. Caption: {repr(caption)}")
        await update.message.reply_text(
            "To log a meal from a photo, please send the photo with the caption `/log meal`."
        )
        return

    logger.info(f"_handle_photo_log: Detected photo with '/log meal' caption.")
    sheet_id = sheet_config['google_sheet_id']
    worksheet_name = sheet_config['worksheet_name']
    column_map = sheet_config['column_map'] # Get the column map

    # --- Send processing message ---
    logger.info(f"_handle_photo_log: Sending processing message using bot {bot_token_snippet}")
    processing_message = await correct_bot.send_message(
        chat_id,
        "Processing meal image... hang tight!"
    )

    try:
        # --- Photo processing logic (moved from original function) ---
        photo = update.message.photo[-1]
        logger.info(f"_handle_photo_log: Getting photo file using bot {bot_token_snippet}")
        photo_file = await correct_bot.get_file(photo.file_id)

        photo_data_bytearray = await photo_file.download_as_bytearray()
        photo_data_bytes = bytes(photo_data_bytearray)
        logger.info(f"_handle_photo_log: Downloaded photo ({len(photo_data_bytes)} bytes).")

        logger.info("_handle_photo_log: Calling parse_meal_image_with_gemini...")
        parsed_items = parse_meal_image_with_gemini(photo_data_bytes)
        logger.info(f"_handle_photo_log: parse_meal_image_with_gemini result: {parsed_items}")

        if not parsed_items:
            await processing_message.edit_text("Sorry, I couldn't identify food items...")
            return

        parsed_items_str = "\n".join([f"- {i['item']} ({i['quantity_g']:.0f}g)" for i in parsed_items])
        await processing_message.edit_text(f"Parsed items:\n{parsed_items_str}\n\nLooking up nutrition...")

        logger.info("_handle_photo_log: Calling get_nutrition_for_items...")
        nutrition_info = get_nutrition_for_items(parsed_items)
        logger.info(f"_handle_photo_log: get_nutrition_for_items result: {nutrition_info}")

        if not nutrition_info:
            await processing_message.edit_text("Sorry, I couldn't retrieve nutritional information...")
            return

        target_date = date.today() # Default to today for direct photo log
        sheet_date_str = format_date_for_sheet(target_date)
        logger.info("_handle_photo_log: Calling add_nutrition...")
        success = add_nutrition(
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
            target_dt=target_date,
            bot_token=correct_bot.token,
            calories=nutrition_info.get('calories', 0),
            p=nutrition_info.get('protein', 0),
            c=nutrition_info.get('carbs', 0),
            f=nutrition_info.get('fat', 0),
            fi=nutrition_info.get('fiber', 0)
        )
        logger.info(f"_handle_photo_log: add_nutrition result: {success}")

        if success:
            response_text = (
                f"✅ Meal logged for {sheet_date_str}!\n"
                f"Added: {nutrition_info.get('calories', 0):.0f} Cal, "
                f"{int(nutrition_info.get('protein', 0))}g P, "
                f"{int(nutrition_info.get('carbs', 0))}g C, "
                f"{int(nutrition_info.get('fat', 0))}g F, "
                f"{int(nutrition_info.get('fiber', 0))}g Fi"
            )
            await processing_message.edit_text(response_text)
        else:
            await processing_message.edit_text("❌ Failed to log meal nutrition to Google Sheet.")
        # --- End of photo processing logic ---

    except Exception as e:
        logger.error(f"_handle_photo_log: Unexpected error during photo processing: {e}", exc_info=True)
        try:
            await processing_message.edit_text("Sorry, an unexpected error occurred while processing the photo.")
        except Exception as report_err:
            logger.error(f"_handle_photo_log: Failed to report photo processing error to user: {report_err}")


# --- Helper: Text Log Handling ---
async def _handle_text_log(update: Update, context: ContextTypes.DEFAULT_TYPE, sheet_config: dict, correct_bot: Bot):
    """Handles logging when a text message starts with /log."""
    chat_id = update.effective_chat.id
    command_text = update.message.text
    bot_token_snippet = correct_bot.token[:6] + "..." if correct_bot.token else "Unknown"
    sheet_id = sheet_config['google_sheet_id']
    worksheet_name = sheet_config['worksheet_name']
    column_map = sheet_config['column_map'] # Get the column map

    # --- Argument Extraction (from original function) ---
    parts = (command_text or "").split()
    args = parts[1:] if parts else []
    logger.info(f"_handle_text_log: Extracted args: {args}")
    # --------------------------------

    if not args:
        await update.message.reply_text("Please provide arguments for the /log command. Use /help for details.")
        return

    # --- Date Parsing and Argument Splitting (from original function) ---
    target_date: date = date.today()
    metric_type = ""
    value_args = []
    potential_date_str = args[0]
    metric_start_index = 0

    if len(args) > 1 and (args[1].lower() == 'meal' or args[1].lower() in LOGGING_CHOICES_MAP):
        parsed_dt = dateparser.parse(potential_date_str, settings={'PREFER_DATES_FROM': 'past', 'STRICT_PARSING': False})
        if parsed_dt:
            target_date = parsed_dt.date()
            metric_start_index = 1
            logger.info(f"_handle_text_log: Parsed date: {target_date} from '{potential_date_str}'")
        else:
            logger.info(f"_handle_text_log: Could not parse '{potential_date_str}' as date. Defaulting to today.")
            metric_start_index = 0
    else:
        logger.info("_handle_text_log: Second arg not metric or only one arg. Defaulting date to today.")
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
    sheet_date_str = format_date_for_sheet(target_date)
    # ------------------------------------------------------

    try:
        # --- Handle TEXT Meal Log ---
        if metric_type == 'meal':
            if not value_or_description:
                await update.message.reply_text(
                    "Please provide a meal description after 'meal'. Example:\n"
                    "/log meal 150g chicken breast and 1 cup broccoli"
                )
                return

            logger.info(f"_handle_text_log: Processing meal text: {value_or_description}")

            # Send processing message
            processing_message = await update.message.reply_text(
                f"Processing meal for {sheet_date_str}... hang tight!"
            )

            # Parse meal text
            parsed_items = parse_meal_text_with_gemini(value_or_description)
            if not parsed_items:
                await processing_message.edit_text(
                    "Sorry, I couldn't understand the food items. Please try again or use /newlog for a guided experience."
                )
                return

            # Show parsed items
            parsed_items_str = "\n".join([f"- {i['item']} ({i['quantity_g']:.0f}g)" for i in parsed_items])
            await processing_message.edit_text(f"Parsed items:\n{parsed_items_str}\n\nLooking up nutrition...")

            # Get nutrition info
            nutrition_info = get_nutrition_for_items(parsed_items)
            if not nutrition_info:
                await processing_message.edit_text(
                    "Sorry, I couldn't retrieve nutritional information. Please try again or use /newlog for a guided experience."
                )
                return

            # Add to sheet
            success = add_nutrition(
                sheet_id=sheet_id,
                worksheet_name=worksheet_name,
                target_dt=target_date,
                bot_token=correct_bot.token,
                calories=nutrition_info.get('calories', 0),
                p=nutrition_info.get('protein', 0),
                c=nutrition_info.get('carbs', 0),
                f=nutrition_info.get('fat', 0),
                fi=nutrition_info.get('fiber', 0)
            )

            if success:
                response_text = (
                    f"✅ Meal logged for {sheet_date_str}!\n"
                    f"Added: {nutrition_info.get('calories', 0):.0f} Cal, "
                    f"{int(nutrition_info.get('protein', 0))}g P, "
                    f"{int(nutrition_info.get('carbs', 0))}g C, "
                    f"{int(nutrition_info.get('fat', 0))}g F, "
                    f"{int(nutrition_info.get('fiber', 0))}g Fi\n\n"
                    f"Note: For confirmation and editing options, use /newlog next time."
                )
                await processing_message.edit_text(response_text)
            else:
                await processing_message.edit_text("❌ Failed to log meal nutrition to Google Sheet.")
            return

        # --- Handle Other Metrics ---
        elif metric_type in LOGGING_CHOICES_MAP:
            metric_info = LOGGING_CHOICES_MAP[metric_type]
            input_type = metric_info['type']
            metric_keys = metric_info['metrics'] # Get the standardized keys
            logger.info(f"_handle_text_log: Processing metric '{metric_type}' with input type '{input_type}'")

            # --- Logic for different metric types (moved from original function) ---
            if input_type == 'text_single':
                # Resolve the single column index dynamically
                col_idx = column_map.get(metric_keys[0])
                if col_idx is None:
                     logger.error(f"Schema Error: Column key '{metric_keys[0]}' not found in map for bot {correct_bot.token[:6]}...")
                     await update.message.reply_text(f"❌ Schema configuration error for '{metric_type}'.")
                     return
                metric_value = float(value_or_description) if input_type == 'numeric_single' else value_or_description
                success = update_metrics(
                    sheet_id=sheet_id,
                    worksheet_name=worksheet_name,
                    target_dt=target_date,
                    metric_updates={col_idx: metric_value}, # Pass resolved index
                    bot_token=correct_bot.token
                )
                if success:
                    await update.message.reply_text(f"✅ Updated '{metric_type}' to '{value_or_description}' for {sheet_date_str}.")
                else:
                    await update.message.reply_text(f"❌ Failed to update '{metric_type}' in Google Sheet.")

            elif input_type == 'numeric_single':
                try:
                    value = float(value_or_description)
                    success = update_metrics(
                        sheet_id=sheet_id,
                        worksheet_name=worksheet_name,
                        target_dt=target_date,
                        metric_updates={metric_keys[0]: value},
                        bot_token=correct_bot.token
                    )
                    if success:
                        await update.message.reply_text(f"✅ Updated '{metric_type}' to '{value}' for {sheet_date_str}.")
                    else:
                        await update.message.reply_text(f"❌ Failed to update '{metric_type}' in Google Sheet.")
                except ValueError:
                    await update.message.reply_text(f"/log: Invalid numeric value '{value_or_description}' for '{metric_type}'.")

            elif input_type == 'numeric_multi':
                try:
                    values = [float(v) for v in value_or_description.split()]
                    if len(values) != len(metric_keys):
                        await update.message.reply_text(f"/log: Expected {len(metric_keys)} values for '{metric_type}', got {len(values)}.")
                        return
                    # Resolve multiple column indices dynamically
                    updates = {}
                    for key, val in zip(metric_keys, values):
                        col_idx = column_map.get(key)
                        if col_idx is None:
                            logger.error(f"Schema Error: Column key '{key}' not found in map for bot {correct_bot.token[:6]}...")
                            await update.message.reply_text(f"❌ Schema configuration error for '{metric_type}'.")
                            return # Or handle more gracefully
                        updates[col_idx] = val

                    success = update_metrics(
                        sheet_id=sheet_id,
                        worksheet_name=worksheet_name,
                        target_dt=target_date,
                        metric_updates=updates, # Pass resolved indices
                        bot_token=correct_bot.token
                    )
                    if success:
                        await update.message.reply_text(f"✅ Updated '{metric_type}' values for {sheet_date_str}.")
                    else:
                        await update.message.reply_text(f"❌ Failed to update '{metric_type}' in Google Sheet.")
                except ValueError:
                    await update.message.reply_text(f"/log: Invalid numeric values for '{metric_type}'. Please provide space-separated numbers.")

            elif input_type == 'weight_time':
                # Resolve weight and time columns dynamically
                weight_col_key = metric_keys[0] # e.g., 'WEIGHT_COL_IDX'
                time_col_key = metric_keys[1] # e.g., 'WEIGHT_TIME_COL_IDX'
                weight_col_idx = column_map.get(weight_col_key)
                time_col_idx = column_map.get(time_col_key)
                if weight_col_idx is None or time_col_idx is None:
                     logger.error(f"Schema Error: Weight/Time column keys not found in map for bot {correct_bot.token[:6]}...")
                     await update.message.reply_text(f"❌ Schema configuration error for '{metric_type}'.")
                     return

                parts = value_or_description.split()
                try:
                    weight = float(parts[0])
                    weight_time = parts[1] if len(parts) > 1 else None
                    updates = {weight_col_idx: weight}
                    if weight_time:
                        updates[time_col_idx] = weight_time
                    success = update_metrics(
                        sheet_id=sheet_id,
                        worksheet_name=worksheet_name,
                        target_dt=target_date,
                        metric_updates=updates, # Pass resolved indices
                        bot_token=correct_bot.token
                    )
                    if success:
                        await update.message.reply_text(f"✅ Updated weight to '{weight}'" + (f" at {weight_time}" if weight_time else "") + f" for {sheet_date_str}.")
                    else:
                        await update.message.reply_text(f"❌ Failed to update weight in Google Sheet.")
                except ValueError:
                    await update.message.reply_text(f"/log: Invalid weight value '{parts[0]}'.")
                except IndexError:
                    await update.message.reply_text(f"/log: Error processing weight input: '{value_or_description}'")
            # --- End of logic for different metric types ---
        else:
            # Metric type not 'meal' and not in LOGGING_CHOICES_MAP
            await update.message.reply_text(f"/log: Unknown metric type '{metric_type}'. Use /help.")

    except Exception as e:
        logger.error(f"_handle_text_log: Error processing /log command: {e}", exc_info=True)
        await update.message.reply_text("😥 /log: Internal error occurred while processing text command.")


# --- Main /log Command Entry Point (Dispatcher) ---
async def log_command_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the direct /log command by dispatching to specific handlers."""
    logger.info(f"log_command_entry dispatcher triggered.")

    # --- Initial Setup ---
    sheet_config = _get_current_sheet_config(update)
    if not sheet_config:
        await update.message.reply_text("Sorry, this bot is not configured correctly. Please contact the administrator.")
        return

    correct_bot = getattr(update, '_bot', None)
    if not correct_bot:
         logger.error(f"Could not access update._bot in log_command_entry dispatcher for update {update.update_id}.")
         await update.message.reply_text("Internal error: Bot context missing.")
         return
    # --------------------

    # --- Dispatch based on update type ---
    if update.message.photo:
        logger.info("log_command_entry dispatcher: Detected photo, calling _handle_photo_log.")
        await _handle_photo_log(update, context, sheet_config, correct_bot)
    elif update.message.text:
        logger.info("log_command_entry dispatcher: Detected text, calling _handle_text_log.")
        await _handle_text_log(update, context, sheet_config, correct_bot)
    else:
        # Should not happen if filters are correct, but good to log
        logger.warning(f"log_command_entry dispatcher: Received update without photo or text. Update: {update}")
    # ----------------------------------


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles any command that doesn't match the known commands."""
    await update.message.reply_text(
        "Sorry, I didn't understand that command. Type /help to see available commands."
    ) 