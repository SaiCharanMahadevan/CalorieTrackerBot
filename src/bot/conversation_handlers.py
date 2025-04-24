import logging
from typing import Optional, Dict, Any
from datetime import date
import dateparser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

# Imports from project structure
from src.config.config import LOGGING_CHOICES_MAP
from src.services.sheets_handler import update_metrics, add_nutrition, format_date_for_sheet
from src.services.meal_parser import parse_meal_text_with_gemini, parse_meal_image_with_gemini
from src.services.nutrition_api import get_nutrition_for_items
# Need the helper to get config for the current bot
from .helpers import _get_current_sheet_config
# Import the new audio processor
from src.services.audio_processor import transcribe_audio

logger = logging.getLogger(__name__)

# --- Conversation States ---
(
    SELECTING_ACTION,
    AWAITING_METRIC_CHOICE,
    AWAIT_MEAL_INPUT,
    AWAIT_MEAL_CONFIRMATION,
    AWAIT_METRIC_INPUT,
    ASK_LOG_MORE,
    AWAIT_MACRO_EDIT,
) = range(7)

# Export states for use in main handler definition
CONVERSATION_STATES = {
    SELECTING_ACTION,
    AWAITING_METRIC_CHOICE,
    AWAIT_MEAL_INPUT,
    AWAIT_MEAL_CONFIRMATION,
    AWAIT_METRIC_INPUT,
    ASK_LOG_MORE,
    AWAIT_MACRO_EDIT,
}

# --- Helper Function for Metric Buttons ---
def _get_metric_choice_keyboard():
    """Creates the InlineKeyboardMarkup for choosing metric type."""
    buttons_per_row = 2
    keyboard = [
        [InlineKeyboardButton("Log Meal", callback_data='log_meal')]
    ]
    # Create buttons for non-meal metrics
    metric_buttons = [
        InlineKeyboardButton(f"Log {m.capitalize()}", callback_data=f'log_{m}')
        for m in LOGGING_CHOICES_MAP.keys()
    ]
    # Add metric buttons in pairs
    for i in range(0, len(metric_buttons), buttons_per_row):
         keyboard.append(metric_buttons[i:i + buttons_per_row])
    keyboard.append([InlineKeyboardButton("Finish Session", callback_data='cancel_log')])
    return InlineKeyboardMarkup(keyboard)

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

async def received_metric_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Entering received_metric_choice handler")
    query = update.callback_query
    if not query:
        logger.error("No callback query found in update")
        return ConversationHandler.END

    try:
        await query.answer()
        choice = query.data
        logger.info(f"Processing metric choice: {choice}")

        if choice == 'cancel_log':
            await query.edit_message_text("Logging session cancelled.")
            return ConversationHandler.END

        if choice == 'log_meal':
            logger.info("Selected meal logging")
            await query.edit_message_text("Please describe your meal (e.g., '2 eggs, 1 slice toast, 1 cup coffee').")
            return AWAIT_MEAL_INPUT

        metric_type = choice.replace('log_', '')
        logger.info(f"Processing metric type: {metric_type}")

        if metric_type not in LOGGING_CHOICES_MAP:
            logger.error(f"Unknown metric type received: {metric_type}")
            await query.edit_message_text(
                "Sorry, I encountered an error. Please try again or use /newlog to start over."
            )
            return ConversationHandler.END

        context.user_data['selected_metric'] = metric_type
        metric_info = LOGGING_CHOICES_MAP[metric_type]
        prompt = metric_info['prompt']
        logger.info(f"Setting up prompt for metric: {metric_type}")

        try:
            # First try to delete the message with the keyboard
            await query.message.delete()
            logger.info("Successfully deleted keyboard message")
        except Exception as e:
            logger.error(f"Error deleting keyboard message: {e}")
            # If deletion fails, try to edit instead
            try:
                await query.edit_message_text("Processing...")
                logger.info("Edited message as fallback")
            except Exception as e2:
                logger.error(f"Error editing message: {e2}")

        # --- Get correct bot instance ---
        correct_bot = getattr(update, '_bot', None)
        if not correct_bot:
             logger.error(f"Could not access update._bot in received_metric_choice for update {update.update_id}.")
             await query.edit_message_text("Internal error: Bot context missing. Please try /newlog again.")
             return ConversationHandler.END
        bot_token_snippet = correct_bot.token[:6] + "..." if correct_bot.token else "Unknown"
        # --------------------------------

        try:
            # Send new prompt message using the correct bot instance
            logger.info(f"Attempting to send prompt for {metric_type} using bot {bot_token_snippet}") # <<< Logging updated
            await correct_bot.send_message( # <<< Use correct_bot
                chat_id=update.effective_chat.id,
                text=prompt
            )
            logger.info("Successfully sent prompt message")
        except Exception as e:
            logger.error(f"Error sending prompt message via update._bot ({bot_token_snippet}): {e}", exc_info=True) # <<< Logging updated
            # Attempt to notify user even if sending prompt failed
            try:
                await query.edit_message_text("Error preparing next step. Please try /newlog again.")
            except Exception as report_err:
                 logger.error(f"Failed to report error to user after send_message failed: {report_err}")
            return ConversationHandler.END

        logger.info(f"Transitioning to AWAIT_METRIC_INPUT state for {metric_type}")
        return AWAIT_METRIC_INPUT

    except Exception as e:
        logger.error(f"General error in received_metric_choice: {e}", exc_info=True)
        # Attempt to inform user about the error
        try:
            # Use edit_message_text if possible, otherwise send new message
            if query and query.message:
                await query.edit_message_text("Sorry, something went wrong. Please try /newlog again.")
            elif update.effective_chat:
                 # Need bot instance here too!
                 correct_bot = getattr(update, '_bot', None)
                 if correct_bot:
                    await correct_bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="Sorry, something went wrong. Please try /newlog again."
                    )
                 else:
                    logger.error("Cannot send error message: update._bot is missing in received_metric_choice exception handler.")
        except Exception as report_err:
            logger.error(f"Failed to report error to user: {report_err}")
        return ConversationHandler.END

async def received_metric_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Received metric value input")

    # --- Get correct bot instance EARLY --- 
    correct_bot = getattr(update, '_bot', None)
    if not correct_bot:
         logger.error(f"Could not access update._bot in received_metric_value for update {update.update_id}.")
         await update.message.reply_text("Internal error: Bot context missing. Please try /newlog again.")
         return ConversationHandler.END
    # ------------------------------------

    metric_type = context.user_data.get('selected_metric')
    target_date = context.user_data.get('target_date')
    logger.info(f"Processing value for metric: {metric_type}, date: {target_date}")
    
    if not metric_type or not target_date:
        logger.error("Missing context data in received_metric_value")
        await update.message.reply_text("Error: Missing context. Please start over with /newlog")
        return ConversationHandler.END
        
    # --- Get Sheet Config & Column Map --- #
    sheet_config = _get_current_sheet_config(update)
    if not sheet_config:
        await update.message.reply_text("Sorry, bot configuration error.")
        return ConversationHandler.END # Or some error state
    sheet_id = sheet_config['google_sheet_id']
    worksheet_name = sheet_config['worksheet_name']
    column_map = sheet_config['column_map'] # Get the specific column map
    # --------------------------------------

    metric_info = LOGGING_CHOICES_MAP[metric_type]
    input_type = metric_info['type']
    metric_keys = metric_info['metrics'] # Get standardized keys
    num_values_expected = metric_info['num_values']
    sheet_date_str = format_date_for_sheet(target_date)
    logger.info(f"Input type: {input_type}")

    metric_updates_dict = {}

    try:
        if input_type == 'text_single':
            col_key = metric_keys[0]
            col_idx = column_map.get(col_key)
            if col_idx is None:
                logger.error(f"Schema Error: Key '{col_key}' not found.")
                raise ValueError(f"Schema config error for {metric_type}")
            metric_updates_dict = {col_idx: update.message.text}

        elif input_type == 'numeric_single':
            col_key = metric_keys[0]
            col_idx = column_map.get(col_key)
            if col_idx is None:
                logger.error(f"Schema Error: Key '{col_key}' not found.")
                raise ValueError(f"Schema config error for {metric_type}")
            try:
                value = float(update.message.text)
                metric_updates_dict = {col_idx: value}
            except ValueError:
                await update.message.reply_text(f"Invalid numeric value. Please enter a number.")
                return AWAIT_METRIC_INPUT

        elif input_type == 'numeric_multi':
            try:
                values = [float(v) for v in update.message.text.split()]
                if len(values) != len(metric_keys):
                    await update.message.reply_text(f"Expected {len(metric_keys)} values, got {len(values)}. Please try again.")
                    return AWAIT_METRIC_INPUT
                temp_updates = {}
                for key, val in zip(metric_keys, values):
                    col_idx = column_map.get(key)
                    if col_idx is None:
                        logger.error(f"Schema Error: Key '{key}' not found.")
                        raise ValueError(f"Schema config error for {metric_type}")
                    temp_updates[col_idx] = val
                metric_updates_dict = temp_updates
            except ValueError:
                await update.message.reply_text(f"Invalid numeric values. Please provide space-separated numbers.")
                return AWAIT_METRIC_INPUT

        elif input_type == 'weight_time':
            weight_col_key = metric_keys[0]
            time_col_key = metric_keys[1]
            weight_col_idx = column_map.get(weight_col_key)
            time_col_idx = column_map.get(time_col_key)
            if weight_col_idx is None or time_col_idx is None:
                 logger.error(f"Schema Error: Weight/Time keys missing.")
                 raise ValueError(f"Schema config error for {metric_type}")
            parts = update.message.text.split()
            try:
                weight = float(parts[0])
                weight_time = parts[1] if len(parts) > 1 else None
                temp_updates = {weight_col_idx: weight}
                if weight_time:
                    temp_updates[time_col_idx] = weight_time
                metric_updates_dict = temp_updates
            except ValueError:
                await update.message.reply_text(f"Invalid weight value. Please enter a number, optionally followed by time (e.g., '85.5 0930').")
                return AWAIT_METRIC_INPUT
            except IndexError:
                await update.message.reply_text(f"Error processing weight input: '{update.message.text}'. Please enter weight [time].")
                return AWAIT_METRIC_INPUT

        # --- Call update_metrics AFTER processing all types ---
        if metric_updates_dict:
            logger.info(f"Calling update_metrics for {metric_type} with updates: {metric_updates_dict}")
            success = update_metrics(
                sheet_id=sheet_id,
                worksheet_name=worksheet_name,
                target_dt=target_date,
                metric_updates=metric_updates_dict,
                bot_token=correct_bot.token
            )
            if success:
                # Use a generic success message or tailor based on type if needed
                await update.message.reply_text(f"✅ Updated '{metric_type}' for {sheet_date_str}.")
            else:
                await update.message.reply_text(f"❌ Failed to update '{metric_type}' in Google Sheet.")
        else:
            # Should not happen if logic above is correct, but good to handle
            logger.warning(f"No metric updates generated for input type {input_type}")
            await update.message.reply_text(f"Could not process input for '{metric_type}'.")

        await ask_log_more(update, context)
        return ASK_LOG_MORE

    except ValueError as ve:
        # Handle schema config errors specifically
        logger.error(f"Schema configuration error processing {metric_type}: {ve}")
        await update.message.reply_text(f"❌ Internal configuration error for '{metric_type}'. Please contact the admin.")
        return ConversationHandler.END # End on config errors
    except Exception as e:
        logger.error(f"Error processing metric value for {metric_type}: {e}", exc_info=True)
        await update.message.reply_text("😥 An error occurred while processing your input.")
        # End conversation on unexpected error
        return ConversationHandler.END

async def received_meal_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    target_date = context.user_data.get('target_date')
    if not target_date:
        await update.message.reply_text("Error: Missing date context. Please start over with /newlog")
        return ConversationHandler.END
    sheet_date_str = format_date_for_sheet(target_date)
    
    # --- Get correct bot instance --- 
    correct_bot = getattr(update, '_bot', None)
    if not correct_bot:
         logger.error(f"Could not access update._bot in received_meal_description for update {update.update_id}.")
         await update.message.reply_text("Internal error: Bot context missing.")
         return ConversationHandler.END
    bot_token_snippet = correct_bot.token[:6] + "..." if correct_bot.token else "Unknown"
    # --------------------------------
    
    processing_message = await correct_bot.send_message(
        chat_id,
        f"Processing your input for {sheet_date_str}... hang tight!"
    )

    parsed_items = None
    transcript = None # Variable to hold transcript if audio is processed

    # --- Handle different input types --- #
    try:
        if update.message.text:
            # Process text description (existing logic)
            meal_text = update.message.text
            logger.info(f"Parsing meal text: {meal_text}")
            await processing_message.edit_text(f"Parsing description: \"{meal_text[:30]}...\" for {sheet_date_str}")
            parsed_items = parse_meal_text_with_gemini(meal_text or " ")

        elif update.message.voice or update.message.audio:
            # Process voice/audio message
            logger.info(f"Processing {'voice' if update.message.voice else 'audio'} message.")
            await processing_message.edit_text(f"Transcribing audio for {sheet_date_str}...")
            
            audio_obj = update.message.voice or update.message.audio
            audio_file = await correct_bot.get_file(audio_obj.file_id)
            audio_data_bytearray = await audio_file.download_as_bytearray()
            audio_bytes = bytes(audio_data_bytearray)
            logger.info(f"Downloaded audio ({len(audio_bytes)} bytes).")

            # Transcribe audio
            transcript = await transcribe_audio(audio_bytes)

            if not transcript:
                logger.warning("Audio transcription failed or returned empty.")
                await processing_message.edit_text("Sorry, I couldn't transcribe the audio. Please try describing the meal in text.")
                return AWAIT_MEAL_INPUT # Allow retry with text

            logger.info(f"Audio transcribed. Parsing transcript: {transcript[:50]}...")
            await processing_message.edit_text(f"Parsing transcript: \"{transcript[:30]}...\" for {sheet_date_str}")
            parsed_items = parse_meal_text_with_gemini(transcript)

        elif update.message.photo:
            # Process photo (existing logic)
            logger.info("Processing photo message.")
            await processing_message.edit_text(f"Processing image for {sheet_date_str}...")
            photo = update.message.photo[-1]
            photo_file = await correct_bot.get_file(photo.file_id)
            photo_data_bytearray = await photo_file.download_as_bytearray()
            photo_data_bytes = bytes(photo_data_bytearray)
            logger.info(f"Downloaded photo ({len(photo_data_bytes)} bytes).")
            
            logger.info(f"Parsing meal image for {sheet_date_str}")
            parsed_items = parse_meal_image_with_gemini(photo_data_bytes)

        else:
            logger.warning("Received unexpected message type in AWAIT_MEAL_INPUT state.")
            await processing_message.edit_text("Please send meal description text, a photo, or a voice message.")
            return AWAIT_MEAL_INPUT

        # --- Common Logic: Check Parsing, Lookup Nutrition, Show Confirmation --- #
        if not parsed_items:
            error_message = "Sorry, I couldn't understand the food items" 
            if transcript:
                 error_message += f" in the transcript: \"{transcript[:50]}...\"."
            elif update.message.photo:
                error_message = "Sorry, I couldn't identify food items in the image."
            else:
                error_message += "."
            error_message += " Please try again."
            await processing_message.edit_text(error_message)
            return AWAIT_MEAL_INPUT # Allow retry

        parsed_items_str = "\n".join([f"- {i['item']} ({i['quantity_g']:.0f}g)" for i in parsed_items])
        message_text = f"Parsed items from your input:\n{parsed_items_str}\n\nLooking up nutrition..."
        await processing_message.edit_text(message_text)

        nutrition_info = get_nutrition_for_items(parsed_items)
        if not nutrition_info:
            await processing_message.edit_text("Sorry, I couldn't retrieve nutritional information. Please try again.")
            return AWAIT_MEAL_INPUT # Allow retry

        context.user_data['nutrition_info'] = nutrition_info
        context.user_data['parsed_items'] = parsed_items

        # --- Construct Confirmation Text --- #
        confirmation_text = (
            f"I parsed this meal for {sheet_date_str}:\n\n"
            f"Items:\n{parsed_items_str}\n\n"
            f"Estimated Nutrition:\n"
            f"- Calories: {nutrition_info.get('calories', 0):.0f}\n"
            f"- Protein: {int(nutrition_info.get('protein', 0))}g\n"
            f"- Carbs: {int(nutrition_info.get('carbs', 0))}g\n"
            f"- Fat: {int(nutrition_info.get('fat', 0))}g\n"
            f"- Fiber: {int(nutrition_info.get('fiber', 0))}g\n\n"
            f"What would you like to do?"
        )
        # --- Escape the text for MarkdownV2 --- #
        escaped_confirmation_text = escape_markdown(confirmation_text, version=2)

        # --- Define Buttons --- #
        keyboard = [
            [
                InlineKeyboardButton("✅ Add Meal", callback_data='confirm_meal_yes'),
                InlineKeyboardButton("✏️ Edit Macros", callback_data='edit_macros'),
                InlineKeyboardButton("❌ Cancel", callback_data='confirm_meal_no')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # --- Send Confirmation Message --- #
        await processing_message.edit_text(
            text=escaped_confirmation_text, # Use escaped text
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return AWAIT_MEAL_CONFIRMATION

    except Exception as e:
        logger.error(f"Error in received_meal_description: {e}", exc_info=True)
        try:
            await processing_message.edit_text("Sorry, an unexpected error occurred while processing your input.")
        except Exception as report_err:
            logger.error(f"Failed to report error to user: {report_err}")
        return ConversationHandler.END # End on error

async def received_meal_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # --- Get correct bot instance EARLY --- #
    correct_bot = getattr(update, '_bot', None)
    if not correct_bot:
         logger.error(f"Could not access update._bot in received_meal_confirmation for update {update.update_id}.")
         # Attempt to edit the message if possible
         try:
             await query.edit_message_text("Internal error: Bot context missing. Please try /newlog again.")
         except Exception as e:
             logger.error(f"Failed to edit message on missing bot context: {e}")
         return ConversationHandler.END
    bot_token_snippet = correct_bot.token[:6] + "..." if correct_bot.token else "Unknown"
    # ------------------------------------

    choice = query.data
    target_date = context.user_data.get('target_date')
    if not target_date:
        await query.edit_message_text("Error: Missing date context. Please start over with /newlog")
        return ConversationHandler.END
    sheet_date_str = format_date_for_sheet(target_date)

    # --- ADD Handler for Edit Macros ---
    if choice == 'edit_macros':
        logger.info(f"User chose to edit macros for date {sheet_date_str}")
        
        # --- Retrieve current values for reference ---
        nutrition_info = context.user_data.get('nutrition_info')
        if not nutrition_info:
            logger.error(f"Could not retrieve nutrition_info from user_data in edit_macros step.")
            await query.edit_message_text("Error: Could not retrieve original values. Please try starting over.")
            return ConversationHandler.END
        
        current_vals_text = (
            f"Current estimated values:\n"
            f" Cal: {nutrition_info.get('calories', 0):.0f}, "
            f" P: {nutrition_info.get('protein', 0):.1f}, "
            f" C: {nutrition_info.get('carbs', 0):.1f}, "
            f" F: {nutrition_info.get('fat', 0):.1f}, "
            f" Fi: {nutrition_info.get('fiber', 0):.1f}\n\n"
        )
        # --- No escaping needed for plain text ---
        # escaped_current_vals = escape_markdown(current_vals_text, version=2) # REMOVED
        # ----------------------------------------------------
        
        # --- Plain text prompt --- 
        prompt_text = (
            f"{current_vals_text}"
            f"**(Note: Calories are calculated automatically from macros)**\n\n"
            f"Please send the **4 corrected values** in this exact order (space-separated):\n"
            f"*Protein* *Carbs* *Fat* *Fiber*\n\n"
            f"Example: `35 40 20 8`\n"
            f"(This means 35g Protein, 40g Carbs, 20g Fat, 8g Fiber)"
        )
        
        await query.edit_message_text(
            prompt_text # Plain text
            # parse_mode=ParseMode.MARKDOWN_V2 # REMOVED
        )
        # -----------------------------------------------------------------
        return AWAIT_MACRO_EDIT
    # -----------------------------------

    # --- Handler for Cancel --- #
    if choice == 'confirm_meal_no':
        await query.edit_message_text("Meal logging cancelled. What would you like to log?")

        reply_markup = _get_metric_choice_keyboard()

        # --- Send message using correct bot (already defined) --- #
        logger.info(f"received_meal_confirmation: Sending metric choice prompt using bot {bot_token_snippet}")
        await correct_bot.send_message(
            update.effective_chat.id,
            "Choose a metric to log:",
            reply_markup=reply_markup
        )
        # ---------------------------------------

        context.user_data.pop('nutrition_info', None)
        context.user_data.pop('parsed_items', None)
        return AWAITING_METRIC_CHOICE

    # --- Handler for Add Meal (Confirm Yes) --- #
    if choice == 'confirm_meal_yes':
        # correct_bot is already defined above
        nutrition_info = context.user_data.get('nutrition_info')
        parsed_items = context.user_data.get('parsed_items')
        if not nutrition_info or not parsed_items:
            await query.edit_message_text("Error: Missing nutrition data. Please start over with /newlog")
            return ConversationHandler.END

        # --- Get Sheet Config for this bot --- #
        sheet_config = _get_current_sheet_config(update)
        if not sheet_config:
            await query.edit_message_text("Sorry, bot configuration error.")
            context.user_data.clear()
            return ConversationHandler.END
        sheet_id = sheet_config['google_sheet_id']
        worksheet_name = sheet_config['worksheet_name']
        # -------------------------------------

        await query.edit_message_text("Adding meal to your log...")

        # Call the actual function to add nutrition (using data from user_data)
        logger.info(f"received_meal_confirmation: Calling add_nutrition for {sheet_date_str}")
        success = add_nutrition(
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
            target_dt=target_date,
            bot_token=correct_bot.token, # Now correct_bot is guaranteed to be defined
            calories=nutrition_info.get('calories', 0),
            p=nutrition_info.get('protein', 0),
            c=nutrition_info.get('carbs', 0),
            f=nutrition_info.get('fat', 0),
            fi=nutrition_info.get('fiber', 0)
        )

        # Edit the message AGAIN with the final result
        if success:
            response_text = (
                f"✅ Meal logged for {sheet_date_str}!\n"
                f"Added: {nutrition_info.get('calories', 0):.0f} Cal, "
                f"{int(nutrition_info.get('protein', 0))}g P, "
                f"{int(nutrition_info.get('carbs', 0))}g C, "
                f"{int(nutrition_info.get('fat', 0))}g F, "
                f"{int(nutrition_info.get('fiber', 0))}g Fi"
            )
            await query.edit_message_text(response_text)
        else:
            await query.edit_message_text(f"❌ Failed to log meal nutrition to the Google Sheet.")

        # Ask to log more after attempting to log
        await ask_log_more(update, context)
        return ASK_LOG_MORE

    # --- Handler for Unexpected --- #
    else:
        logger.warning(f"Received unexpected callback data in meal confirmation: {choice}")
        await query.edit_message_text("Invalid choice. Please try again.")

        # Re-show confirmation or go back?
        # Going back to choosing metric seems safest.
        reply_markup = _get_metric_choice_keyboard()

        # --- Send message using correct bot (already defined) --- #
        logger.info(f"received_meal_confirmation: Sending metric choice (unexpected callback) using bot {bot_token_snippet}")
        await correct_bot.send_message(
            update.effective_chat.id,
            "What would you like to log?",
            reply_markup=reply_markup
        )
        # ---------------------------------------

        return AWAITING_METRIC_CHOICE

# --- NEW Handler for Edited Macros ---
async def received_macro_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user's edited P, C, F, Fi values."""
    logger.info("received_macro_edit: Received edited macro input.")

    # --- Get correct bot instance EARLY --- 
    correct_bot = getattr(update, '_bot', None)
    if not correct_bot:
         logger.error(f"Could not access update._bot in received_macro_edit for update {update.update_id}.")
         await update.message.reply_text("Internal error: Bot context missing. Please try /newlog again.")
         return ConversationHandler.END
    # ------------------------------------

    user_text = update.message.text
    target_date = context.user_data.get('target_date')
    nutrition_info = context.user_data.get('nutrition_info')

    if not target_date or not nutrition_info:
        logger.error("received_macro_edit: Missing context data (target_date or nutrition_info).")
        await update.message.reply_text("Error: Missing context. Please start over with /newlog")
        return ConversationHandler.END
        
    # --- Parse the 4 input values ---
    try:
        parts = user_text.split()
        if len(parts) != 4:
            raise ValueError(f"Expected 4 values, got {len(parts)}.")
        
        # Try converting to float
        edited_p, edited_c, edited_f, edited_fi = [float(p) for p in parts]
        
        # Basic sanity check (optional - prevent negative values?)
        if any(v < 0 for v in [edited_p, edited_c, edited_f, edited_fi]):
             raise ValueError("Macro values cannot be negative.")
             
        logger.info(f"received_macro_edit: Parsed edited values - P:{edited_p}, C:{edited_c}, F:{edited_f}, Fi:{edited_fi}")

    except ValueError as e:
        logger.warning(f"received_macro_edit: Invalid input '{user_text}'. Error: {e}")
        await update.message.reply_text(
            f"Invalid input. Please send 4 numbers separated by spaces: `P C F Fi` (e.g., `35 40 20 8`). Error: {e}",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return AWAIT_MACRO_EDIT # Remain in this state to allow retry
    # -----------------------------------

    # --- Update context.user_data ---
    # Only update P, C, F, Fi. Keep original estimated Calories for potential logging/info.
    context.user_data['nutrition_info']['protein'] = edited_p
    context.user_data['nutrition_info']['carbs'] = edited_c
    context.user_data['nutrition_info']['fat'] = edited_f
    context.user_data['nutrition_info']['fiber'] = edited_fi
    # ---------------------------------

    # --- Get Sheet Config (Needed for add_nutrition) ---
    sheet_config = _get_current_sheet_config(update)
    if not sheet_config:
        await update.message.reply_text("Sorry, bot configuration error occurred while trying to save.")
        context.user_data.clear()
        return ConversationHandler.END
    sheet_id = sheet_config['google_sheet_id']
    worksheet_name = sheet_config['worksheet_name']
    # --------------------------------------------------
    
    # --- Save Edited Data to Sheet ---
    logger.info(f"received_macro_edit: Calling add_nutrition with EDITED values for {format_date_for_sheet(target_date)}")
    success = add_nutrition(
        sheet_id=sheet_id,
        worksheet_name=worksheet_name,
        target_dt=target_date,
        bot_token=correct_bot.token,
        calories=edited_p + edited_c + edited_f + edited_fi,
        p=edited_p,
        c=edited_c,
        f=edited_f,
        fi=edited_fi
    )
    # ---------------------------------

    # --- Final Confirmation --- 
    if success:
        sheet_date_str = format_date_for_sheet(target_date)
        # Construct message based on edited values
        response_text = (
            f"✅ Edited meal macros logged for {sheet_date_str}!\n"
            f"Added: {edited_p:.1f}g P, "
            f"{edited_c:.1f}g C, "
            f"{edited_f:.1f}g F, "
            f"{edited_fi:.1f}g Fi"
        )
        await update.message.reply_text(response_text)
    else:
        await update.message.reply_text(f"❌ Failed to log edited meal nutrition to the Google Sheet.")
    # -------------------------

    # --- Ask to log more ---
    await ask_log_more(update, context)
    return ASK_LOG_MORE
    # -------------------------

async def ask_log_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [
            InlineKeyboardButton("Log More", callback_data='log_more'),
            InlineKeyboardButton("Finish", callback_data='finish_log')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "Would you like to log more items?",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "Would you like to log more items?",
            reply_markup=reply_markup
        )
    return ASK_LOG_MORE

async def ask_log_more_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
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
    if update.callback_query:
        await update.callback_query.message.reply_text("Logging session cancelled.")
    else:
        await update.message.reply_text("Logging session cancelled.")
    context.user_data.clear()
    return ConversationHandler.END 