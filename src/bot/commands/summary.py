"""Handlers for summary commands (/daily_summary, /weekly_summary)."""

import logging
from datetime import date, timedelta
import html
import statistics
from telegram import Update, Bot
from telegram.ext import ContextTypes

# Project imports
from src.services.sheets_handler import format_date_for_sheet, get_data_for_daterange
from src.bot.helpers import _get_current_sheet_config # Relative import from parent

logger = logging.getLogger(__name__)

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

# --- Summary Command Handlers --- 
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