import logging
import html
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
    AWAIT_ITEM_QUANTITY_EDIT, # <-- Add new state
) = range(8) # <-- Update range

# Export states for use in main handler definition
CONVERSATION_STATES = {
    SELECTING_ACTION,
    AWAITING_METRIC_CHOICE,
    AWAIT_MEAL_INPUT,
    AWAIT_MEAL_CONFIRMATION,
    AWAIT_METRIC_INPUT,
    ASK_LOG_MORE,
    AWAIT_MACRO_EDIT,
    AWAIT_ITEM_QUANTITY_EDIT, # <-- Add new state
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

# --- Helper function to display items for editing ---
def _format_items_for_editing(parsed_items: list) -> str:
    """Formats the list of parsed items for display during editing."""
    if not parsed_items:
        return "No items found."
    items_text_list = []
    for idx, item in enumerate(parsed_items):
        # Escape item name for HTML safety
        item_name_safe = html.escape(item['item'])
        quantity = f"{item['quantity_g']:.0f}g"
        # Format as plain text suitable for HTML embedding
        items_text_list.append(f"{idx + 1}. {item_name_safe} ({quantity})")
    return "\n".join(items_text_list)

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

        # --- Check Parsing Result --- #
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

        # --- Store Parsed Items and Transition to Editing State --- #
        context.user_data['parsed_items'] = parsed_items
        logger.info(f"Successfully parsed items for {sheet_date_str}. Stored in user_data. Transitioning to AWAIT_ITEM_QUANTITY_EDIT.")

        # Escape sheet_date_str for HTML
        sheet_date_str_safe = html.escape(sheet_date_str)

        items_display = _format_items_for_editing(parsed_items) # Uses updated function
        # Construct prompt using HTML tags, enhancing readability
        prompt_text_html = (
            f"Okay, here are the items I found for <b>{sheet_date_str_safe}</b>:\n\n"
            f"{items_display}\n\n"
            f"You can now adjust the quantities.\n"
            f"Reply with: <code>item_number new_quantity_g</code>\n"
            f"<i>(Example: <code>1 180</code>)</i>\n\n" # Italicize example
            f"Or type <b>done</b> if the list is correct."
        )

        # Send with HTML parse mode, removing reply_markup
        await processing_message.edit_text(
            text=prompt_text_html,
            parse_mode=ParseMode.HTML # <-- Change parse mode
        )
        return AWAIT_ITEM_QUANTITY_EDIT # <-- Transition to new state

    except Exception as e:
        logger.error(f"Error in received_meal_description: {e}", exc_info=True)
        try:
            await processing_message.edit_text("Sorry, an unexpected error occurred while processing your input\.")
        except Exception as report_err:
            logger.error(f"Failed to report error to user: {report_err}")
        return ConversationHandler.END # End on error

# --- NEW Handler for Item Quantity Edits ---
async def received_item_quantity_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles user input for editing item quantities or finishing."""
    user_input = update.message.text.strip().lower()
    chat_id = update.effective_chat.id
    target_date = context.user_data.get('target_date')
    parsed_items = context.user_data.get('parsed_items')

    # --- Get correct bot instance ---
    correct_bot = getattr(update, '_bot', None)
    if not correct_bot:
         logger.error(f"Could not access update._bot in received_item_quantity_edit for update {update.update_id}.")
         await update.message.reply_text("Internal error: Bot context missing.")
         return ConversationHandler.END
    # --------------------------------

    if not target_date or not parsed_items:
        logger.error("received_item_quantity_edit: Missing context data (target_date or parsed_items).")
        await update.message.reply_text("Error: Missing context. Please start over with /newlog")
        return ConversationHandler.END

    sheet_date_str = format_date_for_sheet(target_date)
    sheet_date_str_escaped = html.escape(sheet_date_str)

    if user_input == 'done':
        logger.info(f"User finished editing quantities for {sheet_date_str}. Proceeding to nutrition lookup.")
        # --- Proceed with Nutrition Lookup and Confirmation ---
        processing_message = await update.message.reply_text("Looking up nutrition for the final items...")

        nutrition_info = get_nutrition_for_items(parsed_items)
        if not nutrition_info:
            await processing_message.edit_text("Sorry, I couldn\'t retrieve nutritional information for the final items\. Please try again or cancel\.")
            # Stay in this state or offer cancel? Let's stay for now.
            # Maybe return AWAIT_MEAL_INPUT? Or offer cancel button?
            # For now, just inform and stay. User can try 'done' again or restart.
            # Re-display items might be good here too.
            items_display = _format_items_for_editing(parsed_items)
            # Use HTML for this prompt too, enhancing readability
            prompt_text_html = (
                f"Failed to get nutrition. Current items:\n\n"
                f"{items_display}\n\n"
                f"You can try editing again or type <code>done</code> to retry nutrition lookup."
            )
            await update.message.reply_text(text=prompt_text_html, parse_mode=ParseMode.HTML) # <-- HTML
            return AWAIT_ITEM_QUANTITY_EDIT

        context.user_data['nutrition_info'] = nutrition_info
        logger.info(f"Successfully calculated nutrition for edited items: {nutrition_info}")

        # --- Construct Confirmation Text (using potentially edited items) ---
        # Escape item names for HTML in the final list display
        final_items_display_list = [f"- {html.escape(i['item'])} ({i['quantity_g']:.0f}g)" for i in parsed_items]
        final_items_display = "\n".join(final_items_display_list)

        # Use HTML tags in confirmation text
        confirmation_text_html = (
            f"Okay, here's the final meal log for <b>{sheet_date_str_escaped}</b>:\n\n"
            f"<b>Items</b>:\n{final_items_display}\n\n"
            f"<b>Estimated Nutrition</b>:\n"
            f"- Calories: {nutrition_info.get('calories', 0):.0f}\n"
            f"- Protein: {int(nutrition_info.get('protein', 0))}g\n"
            f"- Carbs: {int(nutrition_info.get('carbs', 0))}g\n"
            f"- Fat: {int(nutrition_info.get('fat', 0))}g\n"
            f"- Fiber: {int(nutrition_info.get('fiber', 0))}g\n\n"
            f"What would you like to do?"
        )
        # No need for escape_markdown

        # Define Buttons (remain the same)
        keyboard = [
            [
                InlineKeyboardButton("✅ Add Meal", callback_data='confirm_meal_yes'),
                InlineKeyboardButton("✏️ Edit Totals", callback_data='edit_macros'), # Changed label slightly
                InlineKeyboardButton("❌ Cancel", callback_data='confirm_meal_no')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # --- Send Confirmation Message --- #
        await processing_message.edit_text(
            text=confirmation_text_html, # Use HTML text
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML # <-- Change parse mode
        )
        logger.info("Transitioning to AWAIT_MEAL_CONFIRMATION")
        return AWAIT_MEAL_CONFIRMATION

    else:
        # --- Try Parsing Edit Command ---
        try:
            parts = user_input.split()
            if len(parts) != 2:
                raise ValueError("Input must be 'item\_number new\_quantity\_g'\.")

            item_num_str, quantity_str = parts
            item_index = int(item_num_str) - 1 # User sees 1-based index

            if not (0 <= item_index < len(parsed_items)):
                raise ValueError(f"Invalid item number\. Please choose between 1 and {len(parsed_items)}\.")

            # Remove 'g' if present, then convert to float
            quantity_str_cleaned = quantity_str.replace('g', '').strip()
            new_quantity = float(quantity_str_cleaned)

            if new_quantity < 0:
                raise ValueError("Quantity cannot be negative")

            # --- Update the item ---
            original_item = parsed_items[item_index]['item']
            original_qty = parsed_items[item_index]['quantity_g']
            parsed_items[item_index]['quantity_g'] = new_quantity
            context.user_data['parsed_items'] = parsed_items # Save updated list back
            logger.info(f"Updated item {item_index + 1} ('{original_item}') quantity from {original_qty:.0f}g to {new_quantity:.0f}g")

            # --- Re-display the list ---
            items_display = _format_items_for_editing(parsed_items) # Uses updated function
            # Use HTML tags, enhancing readability
            prompt_text_html = (
                f"Updated item <b>{item_index + 1}</b> from the current list:\n\n"
                f"{items_display}\n\n"
                # Clarify action vs format, instruct to type done
                f"Edit another item using <code>item_number new_quantity_g</code>, or type <b>done</b>."
            )

            # Send with HTML parse mode, removing reply_markup
            await update.message.reply_text(
                text=prompt_text_html,
                parse_mode=ParseMode.HTML # <-- Change parse mode
            )
            return AWAIT_ITEM_QUANTITY_EDIT # Remain in this state

        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid edit input '{user_input}': {e}")
            # Escape error message for HTML
            error_msg_safe = html.escape(str(e))
            # Use HTML tags in error response, enhancing readability
            error_text_html = (
                f"Invalid format: {error_msg_safe}\n"
                f"Please use the format <code>item_number new_quantity_g</code>\n"
                f"<i>(Example: <code>1 180</code>)</i> or type <code>done</code>."
            )
            await update.message.reply_text(
                error_text_html,
                parse_mode=ParseMode.HTML # <-- Change parse mode
            )
            return AWAIT_ITEM_QUANTITY_EDIT # Remain in this state
        except Exception as e:
             logger.error(f"Unexpected error processing edit command '{user_input}': {e}", exc_info=True)
             # Use HTML tags and escape error message
             await update.message.reply_text(f"An unexpected error occurred while processing your edit: <i>{html.escape(str(e))}</i>. Please try again or type /cancel.", parse_mode=ParseMode.HTML) # <-- HTML
             return AWAIT_ITEM_QUANTITY_EDIT # Remain in state, allow retry or cancel

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

    # --- Handler for Edit Macros (Now 'Edit Totals') ---
    if choice == 'edit_macros':
        logger.info(f"User chose to edit total macros for date {sheet_date_str}")
        
        # --- Retrieve current values for reference ---
        nutrition_info = context.user_data.get('nutrition_info')
        if not nutrition_info:
            logger.error(f"Could not retrieve nutrition_info from user_data in edit_macros step.")
            await query.edit_message_text("Error: Could not retrieve calculated values. Please try starting over.")
            return ConversationHandler.END
        
        current_vals_text = (
            f"Current calculated values:\n" # Slightly rephrased
            f" Cal: {nutrition_info.get('calories', 0):.0f}, "
            f" P: {nutrition_info.get('protein', 0):.1f}, "
            f" C: {nutrition_info.get('carbs', 0):.1f}, "
            f" F: {nutrition_info.get('fat', 0):.1f}, "
            f" Fi: {nutrition_info.get('fiber', 0):.1f}\n\n"
        )

        # Use HTML tags, enhancing readability
        prompt_text_html = (
            f"{current_vals_text}"
            f"<b>Note: Calories are calculated automatically from macros</b>\n\n"
            # Clarify expected input
            f"If these totals seem incorrect, please send the <b>4 corrected values</b> (Protein Carbs Fat Fiber), separated by spaces.\n\n"
            f"<i>Example: <code>35 40 20 8</code></i>"
            # Removed redundant detail line
        )

        # No need for escape_markdown
        await query.edit_message_text(
            prompt_text_html,
            parse_mode=ParseMode.HTML # <-- Change parse mode
        )
        return AWAIT_MACRO_EDIT # Transition to the existing macro edit handler

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
        parsed_items = context.user_data.get('parsed_items') # Keep parsed items for potential future use/logging?
        if not nutrition_info or not parsed_items: # Check both just in case
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
        logger.info(f"received_meal_confirmation: Calling add_nutrition for {sheet_date_str} with final values")
        success = add_nutrition(
            sheet_id=sheet_id,
            worksheet_name=worksheet_name,
            target_dt=target_date,
            bot_token=correct_bot.token,
            calories=nutrition_info.get('calories', 0), # Use calculated calories
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
        # Escape error message for HTML
        error_msg_safe = html.escape(str(e))
        # Use HTML tags in error response, enhancing readability
        error_text_html = (
            f"Invalid input. Please send <b>4 numbers</b> (Protein Carbs Fat Fiber) separated by spaces.\n"
            f"<i>Example: <code>35 40 20 8</code></i>\n"
            f"Error: {error_msg_safe}"
        )
        await update.message.reply_text(
            error_text_html,
            parse_mode=ParseMode.HTML # <-- Change parse mode
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