"""Handlers for summary commands (/daily_summary, /weekly_summary)."""

import logging
from datetime import date, timedelta
import html
import statistics
from typing import Dict # Import Dict
from telegram import Update, Bot
from telegram.ext import ContextTypes

# Project imports
from src.services.sheets import read_data_range, format_date_for_sheet
from src.bot.helpers import _get_current_sheet_config # Relative import from parent
from src.config.config_loader import get_config 
from src.utils.error_utils import log_error, send_error_message

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
    column_map = sheet_config['column_map'] # Get the column map
    bot_token = correct_bot.token
    # ------------------------

    target_date = date.today()
    target_date_str = format_date_for_sheet(target_date)
    # Define column keys needed for this summary
    column_keys_to_fetch = [
        'CALORIES_COL_IDX', 
        'PROTEIN_COL_IDX', 
        'CARBS_COL_IDX', 
        'FAT_COL_IDX', 
        'FIBER_COL_IDX', 
        'STEPS_COL_IDX'
    ]

    try:
        # Fetch data for today - Pass column_map to the helper
        data = await _fetch_and_process_summary_data(
            update, # Passed for error handling context
            context, # Passed for error handling context
            sheet_id,
            worksheet_name,
            bot_token,
            target_date, # Single date for daily
            target_date, # Single date for daily
            column_keys_to_fetch,
            column_map # Pass the actual map
        )

        if data is None: # Helper returns None on config/fetch error
            # Error message already sent by helper
            return 
        if not data: # Helper returns [] if no rows found for the date
            message = f"No data found for today ({target_date_str})."
        else:
            # Assuming only one row for today, helper returns [[val1, val2,...]]
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                 today_values = data[0]
                 # Map values based on the order defined by column_keys_to_fetch
                 # and the min/max columns used in the fetch
                 today_data = {}
                 try:
                    # Get the actual numeric indices corresponding to the keys needed
                    indices_needed = [column_map[key] for key in column_keys_to_fetch if key in column_map]
                    if not indices_needed:
                         raise ValueError("None of the required column keys found in column_map.")
                         
                    min_fetched_col = min(indices_needed)
                    # Map fetched values back to original keys
                    for i, key in enumerate(column_keys_to_fetch):
                        if key in column_map:
                             actual_col_idx = column_map[key]
                             fetch_index = actual_col_idx - min_fetched_col
                             if 0 <= fetch_index < len(today_values):
                                 today_data[key] = today_values[fetch_index]
                             else:
                                 # This case is less likely if min/max logic is correct
                                 logger.warning(f"Calculated fetch index {fetch_index} out of bounds for key {key} (actual index {actual_col_idx}, min fetched {min_fetched_col}) with fetched values {today_values}")
                                 today_data[key] = None
                        else:
                             # Key requested by summary command not in this bot's config map
                             today_data[key] = None 
                             logger.warning(f"Column key {key} requested by daily_summary not found in column_map.")
                             
                 except KeyError as e:
                     logger.error(f"Daily summary: Key Error accessing column_map: {e}. Keys requested: {column_keys_to_fetch}", exc_info=True)
                     await send_error_message(update, context, f"Configuration error: Missing expected column key {e} in settings.")
                     return
                 except ValueError as e:
                     logger.error(f"Daily summary: Value Error processing columns: {e}. Keys requested: {column_keys_to_fetch}", exc_info=True)
                     await send_error_message(update, context, f"Configuration error: {e}")
                     return

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
            else:
                 message = f"Received unexpected data format for today ({target_date_str})."


        await update.message.reply_html(message) # Use HTML for potential bolding

    except Exception as e:
        logger.error(f"Error in daily_summary_command: {e}", exc_info=True)
        await send_error_message(update, context, "Sorry, an error occurred while fetching today's summary.") # Use send_error_message here too

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
    column_map = sheet_config['column_map'] # Get the column map
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
    # Map keys to names for processing results
    key_to_name_map = {
        'SLEEP_HOURS_COL_IDX': 'sleep',
        'WEIGHT_COL_IDX': 'weight',
        'STEPS_COL_IDX': 'steps',
        'CALORIES_COL_IDX': 'calories'
    }


    try:
        # Fetch data for the week - Pass column_map to the helper
        weekly_data_rows = await _fetch_and_process_summary_data(
            update, # Passed for error handling context
            context, # Passed for error handling context
            sheet_id,
            worksheet_name,
            bot_token,
            start_of_week,
            end_of_week,
            column_keys_to_fetch,
            column_map # Pass the actual map
        )

        if weekly_data_rows is None: # Check for None explicitly (indicates fetch error)
             # Error message already sent by helper
             return
        if not weekly_data_rows: # Check for empty list (no data found)
            await update.message.reply_html(f"No data found for the period {start_date_str} to {end_date_str}.")
            return

        # --- Aggregate data for averaging --- 
        aggregated_values = {name: [] for name in key_to_name_map.values()}
        
        # Determine mapping from fetched index to metric name using the column_map
        try:
             indices_needed = [column_map[key] for key in column_keys_to_fetch if key in column_map]
             if not indices_needed:
                 raise ValueError("None of the required column keys for weekly summary found in column_map.")
                 
             min_fetched_col = min(indices_needed)
             index_to_name = {}
             for key, name in key_to_name_map.items():
                 if key in column_map:
                     actual_col_idx = column_map[key]
                     fetch_index = actual_col_idx - min_fetched_col
                     index_to_name[fetch_index] = name
                 else:
                     logger.warning(f"Column key {key} requested by weekly_summary not found in column_map.")
                     
        except KeyError as e:
             logger.error(f"Weekly summary: Key Error creating index_to_name map: {e}. Keys requested: {column_keys_to_fetch}", exc_info=True)
             await send_error_message(update, context, f"Configuration error: Missing expected column key {e} for weekly summary.")
             return
        except ValueError as e:
             logger.error(f"Weekly summary: Value Error processing columns: {e}. Keys requested: {column_keys_to_fetch}", exc_info=True)
             await send_error_message(update, context, f"Configuration error: {e}")
             return
             
        for row in weekly_data_rows:
             if not isinstance(row, list):
                 logger.warning(f"Weekly summary processing: Expected list row, got {type(row)}. Skipping row.")
                 continue
             for fetch_index, value in enumerate(row):
                 metric_name = index_to_name.get(fetch_index)
                 if metric_name:
                     aggregated_values[metric_name].append(value)
        # ------------------------------------

        # --- Calculate Averages --- 
        avg_sleep = _calculate_average(aggregated_values['sleep'])
        avg_weight = _calculate_average(aggregated_values['weight'])
        avg_steps = _calculate_average(aggregated_values['steps'])
        avg_calories = _calculate_average(aggregated_values['calories'])
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
        await send_error_message(update, context, "Sorry, an error occurred while fetching the weekly summary.") # Use send_error_message here too

async def _fetch_and_process_summary_data(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE, # Add context here
    sheet_id: str,
    worksheet_name: str,
    bot_token: str,
    start_dt: date,
    end_dt: date,
    column_keys: list, # List of keys like 'CALORIES_COL_IDX'
    column_map: Dict[str, int] # Pass the actual map {key: index}
) -> list | None:
    """Fetches and processes summary data for a given date range. 
       Uses the column_map to find actual indices for the requested keys.
       Returns a list of rows (each row is a list of values) or None on error.
    """
    logger.info(f"Fetching summary data for: {start_dt} to {end_dt}. Keys: {column_keys}")
    all_rows_data = []
    
    # --- Determine columns to fetch once using column_map values ---
    try:
        # Get the actual numeric indices from the map for the requested keys
        indices_to_fetch = [column_map[key] for key in column_keys if key in column_map]
        
        if not indices_to_fetch:
            # Check if *any* requested keys were found in the map
            found_keys = [key for key in column_keys if key in column_map]
            if not found_keys:
                 logger.error(f"None of the requested column keys {column_keys} were found in the provided column_map for bot {bot_token[:6]}...")
                 await send_error_message(update, context, f"Configuration error: None of the required columns ({', '.join(column_keys)}) are defined in settings.")
                 return None
            else:
                 # Some keys were found, but maybe not all. Proceed with found keys.
                 logger.warning(f"Some requested column keys were not found in column_map. Found: {found_keys}. Requested: {column_keys}")
                 # indices_to_fetch will contain only the valid ones
                 pass 
                 
        # Determine the min/max range needed to cover all requested valid columns
        min_col = min(indices_to_fetch)
        max_col = max(indices_to_fetch)
        logger.debug(f"Determined fetch range: Min Col={min_col}, Max Col={max_col} based on keys: {column_keys}")
        
    except KeyError as e:
         # This catches cases where a key in column_keys is *not* in column_map during list comprehension
         logger.error(f"KeyError while determining fetch indices: {e}. Requested keys: {column_keys}. Map keys: {list(column_map.keys())}")
         await send_error_message(update, context, f"Configuration error: Column key {e} needed for summary is not defined in settings.")
         return None
    except Exception as e:
         # Catch other potential errors during index processing
         logger.error(f"Error processing column keys/map for summary fetch: {e}. Requested keys: {column_keys}", exc_info=True)
         await send_error_message(update, context, "Internal configuration error processing summary columns.")
         return None
    # --- ---

    current_day = start_dt
    while current_day <= end_dt:
        try:
            # Fetch data for the current day using the new function
            # read_data_range returns a single list for the row, or None
            daily_data = read_data_range(
                sheet_id, worksheet_name, current_day, min_col, max_col, bot_token
            )

            if daily_data is not None: # Check for None (error or not found), not just truthiness
                all_rows_data.append(daily_data)
            # If daily_data is None, it means the row wasn't found or an error occurred reading it.
            # We simply skip that day for the summary calculation. Logging happens in read_data_range.

        except Exception as e:
            # Log unexpected errors during the loop, but try to continue
            logger.error(f"Error fetching data for {current_day} in _fetch_and_process_summary_data loop: {e}", exc_info=True)
            # Do not send message here, as it would spam for every failed day.
            # The final summary will just be based on the days successfully fetched.
        
        current_day += timedelta(days=1) # Move to the next day

    if not all_rows_data:
        logger.info(f"No data found for the date range: {start_dt} to {end_dt}")
        return [] # Return empty list, not None, to indicate no data found vs. error

    return all_rows_data # Return list of lists (rows) 