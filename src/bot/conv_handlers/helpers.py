import html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Imports from project structure (adjust path as needed)
from src.config.config import LOGGING_CHOICES_MAP

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
    """Formats the list of parsed items for display during editing (HTML)."""
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

# --- Helper for Standard HTML Error Replies ---
def format_error_html(error_message: str, suggestion: str = "Please try again or type /cancel.") -> str:
    """Formats a standard error reply using HTML."""
    # Only escape the error message, assume suggestion is safe or already contains HTML
    return f"❌ Error: <i>{html.escape(error_message)}</i>\n{suggestion}"

def format_error_edit_html(error_message: str, command_format: str, example: str) -> str:
    """Formats an error reply specifically for edit commands using HTML."""
    return (
        f"Invalid format: <i>{html.escape(error_message)}</i>\n"
        f"Please use the format <code>{command_format}</code>\n"
        f"<i>(Example: <code>{example}</code>)</i> or type <code>done</code>."
    ) 