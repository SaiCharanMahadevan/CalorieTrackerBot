"""Handlers for direct, non-conversational commands."""

import logging
from datetime import date
import dateparser

import telegram # Keep telegram (used for errors/classes)
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

# Project imports
from src.config.config import LOGGING_CHOICES_MAP, WEIGHT_COL_IDX, WEIGHT_TIME_COL_IDX
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
        " `/log [date] [metric] [value]`: Log data in a single line (see examples below).\n"
        " `/newlog`: Start a guided conversation to log multiple items for a date (Recommended for meals).\n"
        " `/cancel`: Cancel the current logging operation (e.g., during `/newlog`).\n\n"
        "*Using /log:*\n"
        " `/log [optional_date] [metric_type] [value_or_description]`\n"
        " - `optional_date`: E.g., `today`, `yesterday`, `Jul 16`, `2024-07-16`. Defaults to *today*.\n"
        " - `metric_type`: `meal` or one of: METRIC_PLACEHOLDER.\n"
        " - `value_or_description`: Numeric value or meal description.\n\n"
        "*/log Examples:*\n"
        " `/log weight 85.5`\n"
        " `/log yesterday sleep 7.5`\n"
        " `/log Jul 15 meal 150g chicken breast and 1 cup broccoli` (Note: meal logs via /log are added directly without confirmation)\n"
        " `/log meal A quick snack`\n"
        " `/log meal` (with a photo attached) - Log a meal by sending a photo\n\n"
        "*Using /newlog (Conversational):*\n"
        " Just type `/newlog` and follow the prompts. Allows logging multiple items for the chosen date.\n"
        " You can also send a photo of your meal during the meal logging process.\n\n"
        "*Image Upload Feature:*\n"
        " You can now log meals by sending photos:\n"
        " 1. During the `/newlog` conversation, when prompted for meal details\n"
        " 2. Using `/log meal` with a photo attached\n"
        " The bot will analyze the image, identify food items, estimate portions, and calculate nutrition.\n"
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

async def log_command_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the direct /log command, now also checking captions."""
    # --- DIAGNOSTIC LOGGING (UPDATED) --- 
    logger.info(f"log_command_entry triggered.")
    command_text = update.message.text or update.message.caption
    logger.info(f"  Original command text/caption: {repr(command_text)}")
    
    # --- Manual Argument Extraction --- 
    parts = (command_text or "").split()
    args = parts[1:] if parts else [] # args are anything after the /log command itself
    logger.info(f"  Manually extracted args: {args}")
    # --------------------------------

    chat_id = update.effective_chat.id
    # args = context.args # No longer automatically populated by MessageHandler
    logger.info(f"Processing /log command with extracted args: {args}")

    # --- Get Sheet Config for this bot ---
    sheet_config = _get_current_sheet_config(update)
    if not sheet_config:
        # Use update.message.reply_text as it implicitly uses the correct bot
        await update.message.reply_text("Sorry, this bot is not configured correctly. Please contact the administrator.")
        return
    sheet_id = sheet_config['google_sheet_id']
    worksheet_name = sheet_config['worksheet_name']
    # -------------------------------------
    
    # --- Get correct bot instance early ---
    correct_bot = getattr(update, '_bot', None)
    if not correct_bot:
         logger.error(f"Could not access update._bot in log_command_entry for update {update.update_id}.")
         # Use update.message.reply_text as it implicitly uses the correct bot
         await update.message.reply_text("Internal error: Bot context missing.")
         return
    bot_token_snippet = correct_bot.token[:6] + "..." if correct_bot.token else "Unknown"
    # ------------------------------------

    if not args:
        await update.message.reply_text("Please provide arguments for the /log command. Use /help for details.")
        return

    # Check if the message contains a photo and the first argument is 'meal'
    logger.info(f"Update message: {update.message}")
    if update.message.photo and args and args[0].lower() == 'meal':
        # 1. Failure Point: Did this condition even trigger? (Wrong format used?)
        logger.info(f"log_command_entry: Detected photo with '/log meal' caption.") # Added log

        # --- Send message using correct bot ---
        logger.info(f"log_command_entry: Sending processing message using bot {bot_token_snippet}")
        processing_message = await correct_bot.send_message( # <<< Use correct_bot
            chat_id,
            "Processing meal image... hang tight!"
        )
        # ---------------------------------------

        try: # Added try block for more specific error logging in photo path
            # Get the largest photo (best quality)
            photo = update.message.photo[-1]

            # --- Get file using correct bot ---
            logger.info(f"log_command_entry: Getting photo file using bot {bot_token_snippet}")
            photo_file = await correct_bot.get_file(photo.file_id) # <<< Use correct_bot
            # 2. Failure Point: Telegram API error getting file?
            # ---------------------------------

            photo_data_bytearray = await photo_file.download_as_bytearray()
            photo_data_bytes = bytes(photo_data_bytearray) # Convert to bytes
            logger.info(f"log_command_entry: Downloaded photo ({len(photo_data_bytes)} bytes).") # Added log

            # Parse the meal image
            # 3. Failure Point: Gemini parsing (API key, image clarity, API error)
            logger.info("log_command_entry: Calling parse_meal_image_with_gemini...") # Added log
            parsed_items = parse_meal_image_with_gemini(photo_data_bytes)
            logger.info(f"log_command_entry: parse_meal_image_with_gemini result: {parsed_items}") # Added log

            if not parsed_items:
                await processing_message.edit_text("Sorry, I couldn't identify food items in the image. Please try again with a clearer photo or describe the meal in text.")
                return

            # Get nutrition info
            parsed_items_str = "\n".join([f"- {i['item']} ({i['quantity_g']:.0f}g)" for i in parsed_items])
            message_text = f"Parsed items:\n{parsed_items_str}\n\nLooking up nutrition..."
            await processing_message.edit_text(message_text)

            # 4. Failure Point: Nutrition API lookup (API key, API error)
            logger.info("log_command_entry: Calling get_nutrition_for_items...") # Added log
            nutrition_info = get_nutrition_for_items(parsed_items)
            logger.info(f"log_command_entry: get_nutrition_for_items result: {nutrition_info}") # Added log

            if not nutrition_info:
                await processing_message.edit_text("Sorry, I couldn't retrieve nutritional information. Please try again.")
                return

            # Add nutrition to sheet
            target_date = date.today()  # Default to today
            # 5. Failure Point: Google Sheets update (Credentials, API error)
            logger.info("log_command_entry: Calling add_nutrition...") # Added log
            success = add_nutrition(
                sheet_id=sheet_id,
                worksheet_name=worksheet_name,
                target_dt=target_date,
                calories=nutrition_info.get('calories', 0),
                p=nutrition_info.get('protein', 0),
                c=nutrition_info.get('carbs', 0),
                f=nutrition_info.get('fat', 0),
                fi=nutrition_info.get('fiber', 0)
            )
            logger.info(f"log_command_entry: add_nutrition result: {success}") # Added log

            if success:
                sheet_date_str = format_date_for_sheet(target_date)
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
            return

        except Exception as e:
            # Catch unexpected errors specifically within the photo processing block
            logger.error(f"log_command_entry: Unexpected error during photo processing: {e}", exc_info=True)
            try:
                await processing_message.edit_text("Sorry, an unexpected error occurred while processing the photo.")
            except Exception as report_err:
                logger.error(f"log_command_entry: Failed to report photo processing error to user: {report_err}")
            return # Exit after specific error

    # Process regular text-based log command
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
    sheet_date_str = format_date_for_sheet(target_date)

    try:
        if metric_type == 'meal':
            # --- Send message using correct bot ---
            logger.info(f"log_command_entry: Sending meal processing message using bot {bot_token_snippet}")
            await correct_bot.send_message(chat_id, f"Processing meal for {sheet_date_str} (direct log)... hang tight!") # <<< Use correct_bot
            # ---------------------------------------
            
            logger.info(f"/log: Parsing meal: {value_or_description}")
            parsed_items = parse_meal_text_with_gemini(value_or_description or " ")
            if not parsed_items:
                await update.message.reply_text("/log: Sorry, couldn't understand food items.")
                return

            parsed_items_str = "\n".join([f"- {i['item']} ({i['quantity_g']:.0f}g)" for i in parsed_items])
            
            # --- Send message using correct bot ---
            logger.info(f"log_command_entry: Sending parsed items message using bot {bot_token_snippet}")
            await correct_bot.send_message(chat_id, f"Parsed items:\n{parsed_items_str}\n\nLooking up nutrition...", parse_mode=ParseMode.HTML) # <<< Use correct_bot
            # ---------------------------------------

            nutrition_info = get_nutrition_for_items(parsed_items)
            if not nutrition_info:
                await update.message.reply_text("/log: Sorry, couldn't retrieve nutritional info.")
                return

            success = add_nutrition(
                sheet_id=sheet_id,
                worksheet_name=worksheet_name,
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
                    f"Added: {nutrition_info.get('calories', 0):.0f} Cal, "
                    f"{nutrition_info.get('protein', 0):.1f}g P, "
                    f"{nutrition_info.get('carbs', 0):.1f}g C, "
                    f"{nutrition_info.get('fat', 0):.1f}g F, "
                    f"{nutrition_info.get('fiber', 0):.1f}g Fi"
                 )
                 await update.message.reply_text(response_text)
            else:
                await update.message.reply_text("❌ Failed to log meal nutrition to Google Sheet.")

        elif metric_type in LOGGING_CHOICES_MAP:
            metric_info = LOGGING_CHOICES_MAP[metric_type]
            input_type = metric_info['type']

            if input_type == 'text_single':
                success = update_metrics(
                    sheet_id=sheet_id,
                    worksheet_name=worksheet_name,
                    target_dt=target_date,
                    metric_updates={metric_info['cols'][0]: value_or_description}
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
                        metric_updates={metric_info['cols'][0]: value}
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
                    if len(values) != len(metric_info['cols']):
                        await update.message.reply_text(f"/log: Expected {len(metric_info['cols'])} values for '{metric_type}', got {len(values)}.")
                        return

                    updates = {col: val for col, val in zip(metric_info['cols'], values)}
                    success = update_metrics(
                        sheet_id=sheet_id,
                        worksheet_name=worksheet_name,
                        target_dt=target_date,
                        metric_updates=updates
                    )
                    if success:
                        await update.message.reply_text(f"✅ Updated '{metric_type}' values for {sheet_date_str}.")
                    else:
                        await update.message.reply_text(f"❌ Failed to update '{metric_type}' in Google Sheet.")
                except ValueError:
                    await update.message.reply_text(f"/log: Invalid numeric values for '{metric_type}'. Please provide space-separated numbers.")

            elif input_type == 'weight_time':
                parts = value_or_description.split()
                try:
                    weight = float(parts[0])
                    weight_time = parts[1] if len(parts) > 1 else None
                    updates = {WEIGHT_COL_IDX: weight}
                    if weight_time:
                        updates[WEIGHT_TIME_COL_IDX] = weight_time
                    success = update_metrics(
                        sheet_id=sheet_id,
                        worksheet_name=worksheet_name,
                        target_dt=target_date,
                        metric_updates=updates
                    )
                    if success:
                        await update.message.reply_text(f"✅ Updated weight to '{weight}'" + (f" at {weight_time}" if weight_time else "") + f" for {sheet_date_str}.")
                    else:
                        await update.message.reply_text(f"❌ Failed to update weight in Google Sheet.")
                except ValueError:
                    await update.message.reply_text(f"/log: Invalid weight value '{parts[0]}'.")
                except IndexError:
                    await update.message.reply_text(f"/log: Error processing weight input: '{value_or_description}'")
        else:
            await update.message.reply_text(f"/log: Unknown metric type '{metric_type}'. Use /help.")

    except Exception as e:
        logger.error(f"Error processing /log command: {e}", exc_info=True)
        await update.message.reply_text("😥 /log: Internal error occurred.")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles any command that doesn't match the known commands."""
    await update.message.reply_text(
        "Sorry, I didn't understand that command. Type /help to see available commands."
    ) 