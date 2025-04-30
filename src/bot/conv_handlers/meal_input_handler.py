import logging
import html
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

# Project imports
from src.services.sheets_handler import format_date_for_sheet
from src.services.meal_parser import parse_meal_text_with_gemini, parse_meal_image_with_gemini
from src.services.audio_processor import transcribe_audio
from src.bot.helpers import _get_current_sheet_config # Main helpers

# Local imports (within conv_handlers)
from .states import AWAIT_MEAL_INPUT, AWAIT_ITEM_QUANTITY_EDIT
from .helpers import _format_items_for_editing

logger = logging.getLogger(__name__)

# --- Internal Input Processing Helpers ---
async def _process_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, processing_message):
    meal_text = update.message.text
    sheet_date_str = format_date_for_sheet(context.user_data['target_date'])
    logger.info(f"Parsing meal text: {meal_text}")
    await processing_message.edit_text(f"Parsing description: \"{meal_text[:30]}...\" for {sheet_date_str}")
    return parse_meal_text_with_gemini(meal_text or " ")

async def _process_audio_input(update: Update, context: ContextTypes.DEFAULT_TYPE, processing_message, correct_bot):
    is_voice = update.message.voice is not None
    audio_type = 'voice' if is_voice else 'audio'
    sheet_date_str = format_date_for_sheet(context.user_data['target_date'])
    logger.info(f"Processing {audio_type} message.")
    await processing_message.edit_text(f"Transcribing audio for {sheet_date_str}...")
    
    audio_obj = update.message.voice or update.message.audio
    audio_file = await correct_bot.get_file(audio_obj.file_id)
    audio_data_bytearray = await audio_file.download_as_bytearray()
    audio_bytes = bytes(audio_data_bytearray)
    logger.info(f"Downloaded audio ({len(audio_bytes)} bytes).")

    # Transcribe audio
    transcript = await transcribe_audio(audio_bytes)
    context.user_data['_transcript'] = transcript # Store for potential error message

    if not transcript:
        logger.warning("Audio transcription failed or returned empty.")
        await processing_message.edit_text("Sorry, I couldn't transcribe the audio. Please try describing the meal in text.")
        return None # Indicate failure

    logger.info(f"Audio transcribed. Parsing transcript: {transcript[:50]}...")
    await processing_message.edit_text(f"Parsing transcript: \"{transcript[:30]}...\" for {sheet_date_str}")
    return parse_meal_text_with_gemini(transcript)

async def _process_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE, processing_message, correct_bot):
    sheet_date_str = format_date_for_sheet(context.user_data['target_date'])
    logger.info("Processing photo message.")
    await processing_message.edit_text(f"Processing image for {sheet_date_str}...")
    photo = update.message.photo[-1]
    photo_file = await correct_bot.get_file(photo.file_id)
    photo_data_bytearray = await photo_file.download_as_bytearray()
    photo_data_bytes = bytes(photo_data_bytearray)
    logger.info(f"Downloaded photo ({len(photo_data_bytes)} bytes).")
    
    logger.info(f"Parsing meal image for {sheet_date_str}")
    return parse_meal_image_with_gemini(photo_data_bytes)


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
    context.user_data.pop('_transcript', None) # Clear previous transcript

    # --- Handle different input types using helpers --- #
    try:
        if update.message.text:
            parsed_items = await _process_text_input(update, context, processing_message)
        elif update.message.voice or update.message.audio:
            parsed_items = await _process_audio_input(update, context, processing_message, correct_bot)
            if parsed_items is None: # Check if audio processing failed (indicated by None)
                 return AWAIT_MEAL_INPUT # Allow retry with text
        elif update.message.photo:
            parsed_items = await _process_photo_input(update, context, processing_message, correct_bot)
        else:
            logger.warning("Received unexpected message type in AWAIT_MEAL_INPUT state.")
            await processing_message.edit_text("Please send meal description text, a photo, or a voice message.")
            return AWAIT_MEAL_INPUT

        # --- Check Parsing Result --- #
        if not parsed_items:
            error_message = "Sorry, I couldn't understand the food items"
            transcript = context.user_data.get('_transcript') # Get transcript if it exists
            if transcript:
                 # Escape transcript for HTML safety in error message
                 safe_transcript_snippet = html.escape(transcript[:50])
                 error_message += f" in the transcript: \"{safe_transcript_snippet}...\"."
            elif update.message.photo:
                error_message = "Sorry, I couldn't identify food items in the image."
            else:
                error_message += "."
            error_message += " Please try again."
            await processing_message.edit_text(error_message)
            context.user_data.pop('_transcript', None) # Clean up transcript
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
            # Updated instruction: type 'done' instead of pressing button
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
        context.user_data.pop('_transcript', None) # Clean up transcript on error
        try:
            # Use HTML
            await processing_message.edit_text(f"Sorry, an unexpected error occurred while processing your input: <i>{html.escape(str(e))}</i>", parse_mode=ParseMode.HTML)
        except Exception as report_err:
            logger.error(f"Failed to report error to user: {report_err}")
        return ConversationHandler.END # End on error 