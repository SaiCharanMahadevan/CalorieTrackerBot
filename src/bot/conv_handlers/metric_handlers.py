import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

# Project imports
from src.config.config import LOGGING_CHOICES_MAP
from src.services.sheets_handler import update_metrics, format_date_for_sheet
# Need the helper to get config for the current bot
from src.bot.helpers import _get_current_sheet_config # Uses the main helpers

# Local imports
from .states import (
    AWAITING_METRIC_CHOICE, AWAIT_MEAL_INPUT, AWAIT_METRIC_INPUT,
    ASK_LOG_MORE
)
from .flow_handlers import ask_log_more # Relative import needs careful handling

logger = logging.getLogger(__name__)


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