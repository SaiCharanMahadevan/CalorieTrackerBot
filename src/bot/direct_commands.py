"""Handlers for direct, non-conversational commands."""

import logging
from datetime import date, timedelta
import dateparser
import html
import statistics

import telegram # Keep telegram (used for errors/classes)
from telegram import Update, Bot
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# Project imports
from src.config.config import LOGGING_CHOICES_MAP # Keep this one
from src.services.sheets_handler import (
    update_metrics, 
    add_nutrition, 
    format_date_for_sheet, 
    get_data_for_daterange # Import new function
)
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

            if input_type == 'text_single':
                # Resolve the single column index dynamically
                col_key = metric_keys[0]
                col_idx = column_map.get(col_key)
                if col_idx is None:
                    logger.error(f"Schema Error: Column key '{col_key}' not found in map for bot {correct_bot.token[:6]}...")
                    await update.message.reply_text(f"❌ Schema configuration error for '{metric_type}'.")
                    return
                # Use the resolved index col_idx
                success = update_metrics(
                    sheet_id=sheet_id,
                    worksheet_name=worksheet_name,
                    target_dt=target_date,
                    metric_updates={col_idx: value_or_description},
                    bot_token=correct_bot.token
                )
                if success:
                    await update.message.reply_text(f"✅ Updated '{metric_type}' to '{value_or_description}' for {sheet_date_str}.")
                else:
                    await update.message.reply_text(f"❌ Failed to update '{metric_type}' in Google Sheet.")

            elif input_type == 'numeric_single':
                 # Resolve the single column index dynamically
                col_key = metric_keys[0]
                col_idx = column_map.get(col_key)
                if col_idx is None:
                    logger.error(f"Schema Error: Column key '{col_key}' not found in map for bot {correct_bot.token[:6]}...")
                    await update.message.reply_text(f"❌ Schema configuration error for '{metric_type}'.")
                    return
                try:
                    value = float(value_or_description)
                    # Use the resolved index col_idx
                    success = update_metrics(
                        sheet_id=sheet_id,
                        worksheet_name=worksheet_name,
                        target_dt=target_date,
                        metric_updates={col_idx: value},
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

# --- Helper Function for Average Calculation ---
def _calculate_average(values: list) -> float | None:
    """Calculates the average of a list, handling non-numeric types and empty lists."""
    numeric_values = []
    for v in values:
        if v is None or v == '':
            continue # Skip None or empty strings
        try:
            # Attempt to convert to float, removing commas if present
            numeric_values.append(float(str(v).replace(',', '')))
        except (ValueError, TypeError):
            logger.warning(f"Could not convert value '{v}' (type: {type(v)}) to float for averaging.")
            continue # Skip values that cannot be converted
            
    if not numeric_values:
        return None # No valid values to average
    return statistics.mean(numeric_values)

# --- New Command Handlers --- 
async def daily_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches and displays the calorie, macro, and step count for today."""
    logger.info(f"daily_summary_command triggered by user {update.effective_user.id}")
    chat_id = update.effective_chat.id
    
    # --- Get Config and Bot --- 
    sheet_config = _get_current_sheet_config(update)
    correct_bot = getattr(update, '_bot', None)
    if not sheet_config or not correct_bot:
        logger.error("Missing config or bot instance in daily_summary_command")
        await update.message.reply_text("Internal configuration error. Please try again later.")
        return
    sheet_id = sheet_config['google_sheet_id']
    worksheet_name = sheet_config['worksheet_name']
    bot_token = correct_bot.token
    # ------------------------

    target_date = date.today()
    target_date_str = format_date_for_sheet(target_date)
    # Update columns to fetch
    column_keys_to_fetch = [
        'CALORIES_COL_IDX', 
        'PROTEIN_COL_IDX', 
        'CARBS_COL_IDX', 
        'FAT_COL_IDX', 
        'FIBER_COL_IDX', 
        'STEPS_COL_IDX'
    ]

    try:
        # Fetch data for today
        data = get_data_for_daterange(
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
            start_dt=target_date,
            end_dt=target_date,
            column_keys=column_keys_to_fetch,
            bot_token=bot_token
        )

        if not data:
            message = f"No data found for today ({target_date_str})."
        else:
            # Assuming only one row for today, get the first result
            today_data = data[0]
            response_lines = [f"📈 <b>Today's Summary ({target_date_str})</b>\n"]

            # Helper to format each metric line
            def format_metric(key: str, label: str, unit: str = '', precision: int = 0) -> str:
                raw_value = today_data.get(key)
                if raw_value is None or str(raw_value).strip() == '':
                    return f"{label}: N/A"
                try:
                    # Convert to float, removing commas
                    value = float(str(raw_value).replace(',', ''))
                    return f"{label}: <b>{value:.{precision}f}{unit}</b>"
                except (ValueError, TypeError):
                    logger.warning(f"Could not convert {label} value '{raw_value}' to float for today.")
                    # Optionally show the raw non-numeric value, escaped
                    escaped_raw = html.escape(str(raw_value))
                    return f"{label}: Invalid ({escaped_raw})"

            # Add lines for each metric
            response_lines.append(format_metric('CALORIES_COL_IDX', "🔥 Calories"))
            response_lines.append(format_metric('PROTEIN_COL_IDX', "💪 Protein", unit='g'))
            response_lines.append(format_metric('CARBS_COL_IDX', "🍞 Carbs", unit='g'))
            response_lines.append(format_metric('FAT_COL_IDX', "🥑 Fat", unit='g'))
            response_lines.append(format_metric('FIBER_COL_IDX', "🥦 Fiber", unit='g'))
            response_lines.append(format_metric('STEPS_COL_IDX', "🚶 Steps"))

            message = "\n".join(response_lines)

        await update.message.reply_html(message) # Use HTML for potential bolding

    except Exception as e:
        logger.error(f"Error in calories_today_command: {e}", exc_info=True)
        await update.message.reply_text("Sorry, an error occurred while fetching today's summary.")

async def weekly_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches and displays the weekly summary (averages)."""
    logger.info(f"weekly_summary_command triggered by user {update.effective_user.id}")
    chat_id = update.effective_chat.id

    # --- Get Config and Bot --- 
    sheet_config = _get_current_sheet_config(update)
    correct_bot = getattr(update, '_bot', None)
    if not sheet_config or not correct_bot:
        logger.error("Missing config or bot instance in weekly_summary_command")
        await update.message.reply_text("Internal configuration error. Please try again later.")
        return
    sheet_id = sheet_config['google_sheet_id']
    worksheet_name = sheet_config['worksheet_name']
    bot_token = correct_bot.token
    # ------------------------

    # --- Calculate Date Range (Sunday to Today) --- 
    today = date.today()
    # Sunday is weekday 6, Monday is 0. timedelta = days to subtract to get to last Sunday.
    days_since_sunday = (today.weekday() + 1) % 7 
    start_of_week = today - timedelta(days=days_since_sunday)
    end_of_week = today # Summary up to today
    
    start_date_str = format_date_for_sheet(start_of_week)
    end_date_str = format_date_for_sheet(end_of_week)
    logger.info(f"Calculating weekly summary for: {start_date_str} to {end_date_str}")
    # -------------------------------------------

    column_keys_to_fetch = [
        'SLEEP_HOURS_COL_IDX', 
        'WEIGHT_COL_IDX', 
        'STEPS_COL_IDX', 
        'CALORIES_COL_IDX'
    ]

    try:
        # Fetch data for the week
        weekly_data = get_data_for_daterange(
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
            start_dt=start_of_week,
            end_dt=end_of_week,
            column_keys=column_keys_to_fetch,
            bot_token=bot_token
        )

        if not weekly_data:
            await update.message.reply_html(f"No data found for the period {start_date_str} to {end_date_str}.")
            return

        # --- Aggregate data for averaging --- 
        sleep_values = [row.get('SLEEP_HOURS_COL_IDX') for row in weekly_data]
        weight_values = [row.get('WEIGHT_COL_IDX') for row in weekly_data]
        steps_values = [row.get('STEPS_COL_IDX') for row in weekly_data]
        calories_values = [row.get('CALORIES_COL_IDX') for row in weekly_data]
        # ------------------------------------

        # --- Calculate Averages --- 
        avg_sleep = _calculate_average(sleep_values)
        avg_weight = _calculate_average(weight_values)
        avg_steps = _calculate_average(steps_values)
        avg_calories = _calculate_average(calories_values)
        # --------------------------

        # --- Format Response --- 
        response_lines = [f"📊 <b>Weekly Summary ({start_date_str} - {end_date_str})</b>\n"]
        response_lines.append(f"😴 Avg Sleep: {avg_sleep:.1f} hours" if avg_sleep is not None else "😴 Avg Sleep: N/A")
        response_lines.append(f"⚖️ Avg Weight: {avg_weight:.1f}" if avg_weight is not None else "⚖️ Avg Weight: N/A")
        response_lines.append(f"🚶 Avg Steps: {avg_steps:.0f}" if avg_steps is not None else "🚶 Avg Steps: N/A")
        response_lines.append(f"🔥 Avg Calories: {avg_calories:.0f}" if avg_calories is not None else "🔥 Avg Calories: N/A")
        # -----------------------

        await update.message.reply_html("\n".join(response_lines))

    except Exception as e:
        logger.error(f"Error in weekly_summary_command: {e}", exc_info=True)
        await update.message.reply_text("Sorry, an error occurred while fetching the weekly summary.") 