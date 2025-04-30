import logging
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

# Project imports
from src.services.sheets import format_date_for_sheet
from src.services.nutrition_api import get_nutrition_for_items

# Local imports
from .states import AWAIT_ITEM_QUANTITY_EDIT, AWAIT_MEAL_CONFIRMATION
from .helpers import _format_items_for_editing, format_error_html, format_error_edit_html

logger = logging.getLogger(__name__)


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
            await processing_message.edit_text("Sorry, I couldn't retrieve nutritional information for the final items. Please try again or cancel.")
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
                raise ValueError("Input must be 'item_number new_quantity_g'")

            item_num_str, quantity_str = parts
            item_index = int(item_num_str) - 1 # User sees 1-based index

            if not (0 <= item_index < len(parsed_items)):
                raise ValueError(f"Invalid item number. Please choose between 1 and {len(parsed_items)}")

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
            # Use the new error formatter helper
            error_text_html = format_error_edit_html(
                error_message=str(e),
                command_format="item_number new_quantity_g",
                example="1 180"
            )
            await update.message.reply_text(
                error_text_html,
                parse_mode=ParseMode.HTML # <-- Change parse mode
            )
            return AWAIT_ITEM_QUANTITY_EDIT # Remain in this state
        except Exception as e:
             logger.error(f"Unexpected error processing edit command '{user_input}': {e}", exc_info=True)
             # Use the general error formatter helper
             error_text_html = format_error_html(f"An unexpected error occurred while processing your edit: {str(e)}")
             await update.message.reply_text(error_text_html, parse_mode=ParseMode.HTML) # <-- HTML
             return AWAIT_ITEM_QUANTITY_EDIT # Remain in state, allow retry or cancel 