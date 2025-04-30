"""Handlers for the direct /log command (text and photo)."""

import logging
from datetime import date
import dateparser
from telegram import Update, Bot
from telegram.ext import ContextTypes

# Project imports
from src.config.config import LOGGING_CHOICES_MAP
from src.services.sheets import update_metrics, add_nutrition, format_date_for_sheet
from src.services.meal_parser import parse_meal_text_with_gemini, parse_meal_image_with_gemini
from src.services.nutrition_api import get_nutrition_for_items
# Need the helper to get config for the current bot
from src.bot.helpers import _get_current_sheet_config # Relative import from parent

logger = logging.getLogger(__name__)

# --- Internal Helper for Argument Parsing ---
def _parse_log_arguments(args: list) -> tuple[date, str, list[str]]:
    """Parses arguments for /log, detecting optional date.
    Returns: (target_date, metric_type, value_args)
    """
    target_date: date = date.today()
    metric_type = ""
    value_args = []
    metric_start_index = 0

    if not args:
        return target_date, metric_type, value_args # Return defaults if no args

    potential_date_str = args[0]
    # Check if a date is provided AND there are enough args for metric + value(s)
    if len(args) > 1 and (args[1].lower() == 'meal' or args[1].lower() in LOGGING_CHOICES_MAP):
        parsed_dt = dateparser.parse(potential_date_str, settings={'PREFER_DATES_FROM': 'past', 'STRICT_PARSING': False})
        if parsed_dt:
            target_date = parsed_dt.date()
            metric_start_index = 1
            logger.info(f"_parse_log_arguments: Parsed date: {target_date} from '{potential_date_str}'")
        else:
            logger.info(f"_parse_log_arguments: Could not parse '{potential_date_str}' as date. Defaulting to today.")
            metric_start_index = 0 # Date not parsed, metric is first arg
    else:
        logger.info("_parse_log_arguments: Date not provided or insufficient args. Defaulting date to today.")
        metric_start_index = 0 # No date, metric is first arg

    if len(args) > metric_start_index:
        metric_type = args[metric_start_index].lower()
        value_args = args[metric_start_index + 1:]
        logger.info(f"_parse_log_arguments: Metric='{metric_type}', Values={value_args}")
    else:
        logger.warning("_parse_log_arguments: Could not extract metric type.")
        metric_type = "" # Ensure metric_type is empty if not found
        value_args = []

    return target_date, metric_type, value_args

# --- Internal Helper for Metric Update Processing ---
async def _process_metric_update(
    update: Update, 
    sheet_config: dict, 
    correct_bot: Bot, 
    target_date: date, 
    metric_type: str, 
    value_args: list[str]
):
    """Handles updating non-meal metrics based on parsed type and values."""
    sheet_id = sheet_config['google_sheet_id']
    worksheet_name = sheet_config['worksheet_name']
    column_map = sheet_config['column_map']
    sheet_date_str = format_date_for_sheet(target_date)
    value_or_description = " ".join(value_args)

    if metric_type not in LOGGING_CHOICES_MAP:
        await update.message.reply_text(f"/log: Unknown metric type '{metric_type}'. Use /help.")
        return

    metric_info = LOGGING_CHOICES_MAP[metric_type]
    input_type = metric_info['type']
    metric_keys = metric_info['metrics']
    logger.info(f"_process_metric_update: Processing metric '{metric_type}' with input type '{input_type}'")

    updates = {}
    success = False
    reply_message = ""

    try:
        if input_type == 'text_single':
            col_key = metric_keys[0]
            col_idx = column_map.get(col_key)
            if col_idx is None:
                raise KeyError(f"Schema Error: Column key '{col_key}' not found")
            updates = {col_idx: value_or_description}
            reply_message = f"✅ Updated '{metric_type}' to '{value_or_description}' for {sheet_date_str}."

        elif input_type == 'numeric_single':
            col_key = metric_keys[0]
            col_idx = column_map.get(col_key)
            if col_idx is None:
                raise KeyError(f"Schema Error: Column key '{col_key}' not found")
            value = float(value_or_description)
            updates = {col_idx: value}
            reply_message = f"✅ Updated '{metric_type}' to '{value}' for {sheet_date_str}."

        elif input_type == 'numeric_multi':
            values = [float(v) for v in value_args] # Use value_args here
            if len(values) != len(metric_keys):
                 await update.message.reply_text(f"/log: Expected {len(metric_keys)} values for '{metric_type}', got {len(values)}.")
                 return
            temp_updates = {}
            for key, val in zip(metric_keys, values):
                col_idx = column_map.get(key)
                if col_idx is None:
                    raise KeyError(f"Schema Error: Column key '{key}' not found")
                temp_updates[col_idx] = val
            updates = temp_updates
            reply_message = f"✅ Updated '{metric_type}' values for {sheet_date_str}."

        elif input_type == 'weight_time':
            weight_col_key, time_col_key = metric_keys
            weight_col_idx = column_map.get(weight_col_key)
            time_col_idx = column_map.get(time_col_key)
            if weight_col_idx is None or time_col_idx is None:
                raise KeyError("Schema Error: Weight/Time column keys not found")
            
            weight = float(value_args[0])
            weight_time = value_args[1] if len(value_args) > 1 else None
            temp_updates = {weight_col_idx: weight}
            if weight_time:
                temp_updates[time_col_idx] = weight_time
            updates = temp_updates
            time_str = f" at {weight_time}" if weight_time else ""
            reply_message = f"✅ Updated weight to '{weight}'{time_str} for {sheet_date_str}."

        # Call update_metrics if updates were prepared
        if updates:
            success = update_metrics(
                sheet_id=sheet_id,
                worksheet_name=worksheet_name,
                target_dt=target_date,
                metric_updates=updates,
                bot_token=correct_bot.token
            )
            if success:
                await update.message.reply_text(reply_message)
            else:
                await update.message.reply_text(f"❌ Failed to update '{metric_type}' in Google Sheet.")
        else:
             # Should only happen if input_type logic is incomplete
             logger.error(f"_process_metric_update: No updates generated for metric '{metric_type}', input '{value_or_description}'")
             await update.message.reply_text(f"❌ Internal error processing '{metric_type}'.")

    except ValueError as e:
        logger.warning(f"_process_metric_update: Value error for '{metric_type}' with input '{value_or_description}': {e}")
        await update.message.reply_text(f"/log: Invalid value(s) provided for '{metric_type}'. Error: {e}")
    except KeyError as e:
        logger.error(f"_process_metric_update: {e} for bot {correct_bot.token[:6]}...", exc_info=True)
        await update.message.reply_text(f"❌ Schema configuration error for '{metric_type}'.")
    except Exception as e:
        logger.error(f"_process_metric_update: Unexpected error for '{metric_type}' with input '{value_or_description}': {e}", exc_info=True)
        await update.message.reply_text(f"❌ Unexpected error updating '{metric_type}'.")

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
        success = await add_nutrition(
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
    command_text = update.message.text
    parts = (command_text or "").split()
    args = parts[1:] if parts else []

    if not args:
        await update.message.reply_text("Please provide arguments for the /log command. Use /help for details.")
        return

    # Parse arguments
    target_date, metric_type, value_args = _parse_log_arguments(args)

    if not metric_type:
        await update.message.reply_text("/log: Could not determine metric type. Use /help.")
        return
    
    # Check for missing value args (unless it's a meal)
    if not value_args and metric_type != 'meal':
        await update.message.reply_text(f"/log: Missing value for metric '{metric_type}'.")
        return

    value_or_description = " ".join(value_args)
    sheet_date_str = format_date_for_sheet(target_date)
    sheet_id = sheet_config['google_sheet_id']
    worksheet_name = sheet_config['worksheet_name']

    try:
        if metric_type == 'meal':
            # --- Handle TEXT Meal Log --- (Keep this logic inline for now)
            if not value_or_description:
                await update.message.reply_text(
                    "Please provide a meal description after 'meal'. Example:\n"
                    "/log meal 150g chicken breast and 1 cup broccoli"
                )
                return

            logger.info(f"_handle_text_log: Processing meal text: {value_or_description}")
            processing_message = await update.message.reply_text(f"Processing meal for {sheet_date_str}... hang tight!")

            parsed_items = parse_meal_text_with_gemini(value_or_description)
            if not parsed_items:
                await processing_message.edit_text("Sorry, I couldn't understand the food items. Please try again or use /newlog for a guided experience.")
                return

            parsed_items_str = "\n".join([f"- {i['item']} ({i['quantity_g']:.0f}g)" for i in parsed_items])
            await processing_message.edit_text(f"Parsed items:\n{parsed_items_str}\n\nLooking up nutrition...")

            nutrition_info = get_nutrition_for_items(parsed_items)
            if not nutrition_info:
                await processing_message.edit_text("Sorry, I couldn't retrieve nutritional information. Please try again or use /newlog for a guided experience.")
                return

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
            # --- End Meal Logic ---

        else:
            # --- Handle Other Metrics using helper ---
            await _process_metric_update(
                update, sheet_config, correct_bot, target_date, metric_type, value_args
            )

    except Exception as e:
        logger.error(f"_handle_text_log: Unhandled error processing /log command: {e}", exc_info=True)
        await update.message.reply_text("😥 /log: An internal error occurred.")


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