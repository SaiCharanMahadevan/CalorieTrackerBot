import logging
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

# Project imports
from src.services.sheets_handler import add_nutrition, format_date_for_sheet
from src.bot.helpers import _get_current_sheet_config # Main helpers

# Local imports
from .states import (
    AWAIT_MACRO_EDIT, AWAITING_METRIC_CHOICE, ASK_LOG_MORE
)
from .helpers import _get_metric_choice_keyboard, format_error_html
from .flow_handlers import ask_log_more

logger = logging.getLogger(__name__)

# --- Helper for Final Success Message ---
def _format_log_success_message(sheet_date_str: str, nutrition: dict, edited: bool = False) -> str:
    """Formats the success message after logging nutrition (HTML safe)."""
    prefix = "Edited meal macros" if edited else "Meal"
    calories_val = nutrition.get('calories', 0)
    calories_note = " (recalculated)" if edited else ""
    return (
        f"✅ {prefix} logged for {html.escape(sheet_date_str)}!\n"
        f"Added: {calories_val:.0f} Cal{calories_note}, "
        f"{nutrition.get('protein', 0):.1f}g P, "
        f"{nutrition.get('carbs', 0):.1f}g C, "
        f"{nutrition.get('fat', 0):.1f}g F, "
        f"{nutrition.get('fiber', 0):.1f}g Fi"
    )

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
        
        # Use HTML tags
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
            f"{current_vals_text}" # Assuming this is already safe or plain text
            f"<b>Note: Calories are calculated automatically from macros</b>\n\n"
            # Clarify expected input
            f"If these totals seem incorrect, please send the <b>4 corrected values</b> (Protein Carbs Fat Fiber), separated by spaces.\n\n"
            f"<i>Example: <code>35 40 20 8</code></i>"
        )

        await query.edit_message_text(
            prompt_text_html,
            parse_mode=ParseMode.HTML # <-- Change parse mode
        )
        return AWAIT_MACRO_EDIT # Transition to the existing macro edit handler

    # --- Handler for Cancel --- #
    if choice == 'confirm_meal_no':
        await query.edit_message_text("Meal logging cancelled. What would you like to log?")

        reply_markup = _get_metric_choice_keyboard() # Uses local helper

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
            # Use helper for success message
            response_text = _format_log_success_message(sheet_date_str, nutrition_info)
            await query.edit_message_text(response_text) # Plain text is fine here
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
        # Use the new error formatter helper
        error_text_html = format_error_html(
            error_message=f"Invalid input: {str(e)}",
            suggestion="Please send <b>4 numbers</b> (Protein Carbs Fat Fiber) separated by spaces.\n<i>Example: <code>35 40 20 8</code></i>"
        )
        await update.message.reply_text(
            error_text_html,
            parse_mode=ParseMode.HTML # <-- Change parse mode
        )
        return AWAIT_MACRO_EDIT # Remain in this state to allow retry
    # -----------------------------------

    # --- Update context.user_data --- 
    # Only update P, C, F, Fi. Keep original estimated Calories for potential logging/info.
    # Calculate new calories based on edited macros (standard factors: P=4, C=4, F=9, Fi=2? - using 0 for fiber as it's complex)
    # Note: Using 4/4/9 factors for simplicity. Fiber contribution is ignored here.
    edited_calories = (edited_p * 4) + (edited_c * 4) + (edited_f * 9)
    context.user_data['nutrition_info']['protein'] = edited_p
    context.user_data['nutrition_info']['carbs'] = edited_c
    context.user_data['nutrition_info']['fat'] = edited_f
    context.user_data['nutrition_info']['fiber'] = edited_fi
    context.user_data['nutrition_info']['calories'] = edited_calories # Store recalculated calories
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
        # Send the RECALCULATED calories based on edited macros
        calories=edited_calories,
        p=edited_p,
        c=edited_c,
        f=edited_f,
        fi=edited_fi
    )
    # ---------------------------------

    # --- Final Confirmation --- 
    if success:
        sheet_date_str_safe = html.escape(format_date_for_sheet(target_date))
        # Use helper for success message (mark as edited)
        # Recreate a minimal nutrition dict for the helper
        final_nutrition = {
            'calories': edited_calories,
            'protein': edited_p,
            'carbs': edited_c,
            'fat': edited_f,
            'fiber': edited_fi
        }
        response_text = _format_log_success_message(sheet_date_str_safe, final_nutrition, edited=True)
        await update.message.reply_text(response_text) # Plain text confirmation
    else:
        await update.message.reply_text(f"❌ Failed to log edited meal nutrition to the Google Sheet.")
    # -------------------------

    # --- Ask to log more --- 
    await ask_log_more(update, context)
    return ASK_LOG_MORE
    # -------------------------
