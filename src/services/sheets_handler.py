"""Handles interactions with Google Sheets for storing user data."""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Optional
from src.config.config import SCOPES
from src.config.config_loader import get_config
import gspread
from google.oauth2 import service_account
import threading
from gspread.exceptions import APIError, WorksheetNotFound

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Optimization: Singleton Client & Worksheet Cache ---
_gspread_client: Optional[gspread.Client] = None
_gspread_client_lock = threading.Lock()
_worksheet_cache: Dict[tuple[str, str], gspread.Worksheet] = {}
_worksheet_cache_lock = threading.Lock()

def _get_gspread_client():
    """Authenticates and returns a shared gspread Client object using the single service account."""
    global _gspread_client
    # Check without lock first for performance
    if _gspread_client is not None:
        return _gspread_client
        
    with _gspread_client_lock:
         # Double-check lock
         if _gspread_client is None:
            logger.info("Initializing shared gspread client...")
            config = None # Ensure config is defined for error handling
            try:
                config = get_config() # Get the singleton config

                if not config.service_account_json_string:
                    logger.critical("Service account JSON string not available in config!")
                    raise ValueError("Missing service account credentials in configuration")

                # Parse the JSON string from the config object
                try:
                    service_account_info = json.loads(config.service_account_json_string)
                except json.JSONDecodeError as e:
                    logger.critical(f"Failed to parse service account JSON from config: {e}")
                    log_snippet = config.service_account_json_string[:50] + "..." if config.service_account_json_string and len(config.service_account_json_string) > 50 else "(empty or None)"
                    logger.critical(f"Problematic JSON string snippet from config: {log_snippet}")
                    raise ValueError("Invalid service account JSON in configuration") from e

                # Use the parsed dictionary for credentials
                creds = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=SCOPES
                )
                _gspread_client = gspread.authorize(creds)
                logger.info("Successfully authorized shared gspread client.")

            except Exception as e:
                logger.error(f"Error initializing shared gspread client: {e}", exc_info=True)
                # Prevent assignment of partially initialized client
                _gspread_client = None # Explicitly reset
                raise # Re-raise exception
                
    # Check again after attempting initialization inside lock
    if _gspread_client is None:
         # Should not happen if exceptions are raised correctly
         raise RuntimeError("Failed to initialize gspread client after lock attempt")
    return _gspread_client

def _get_worksheet(sheet_id: str, worksheet_name: str) -> Optional[gspread.Worksheet]:
    """Gets a specific Worksheet object by ID and name, using caching."""
    cache_key = (sheet_id, worksheet_name)
    
    # Check cache first (without lock for performance)
    cached_ws = _worksheet_cache.get(cache_key)
    if cached_ws is not None:
        logger.debug(f"Returning cached worksheet for key: {cache_key}")
        return cached_ws
        
    # If not in cache, acquire lock to fetch/create
    with _worksheet_cache_lock:
        # Double-check cache inside lock
        cached_ws = _worksheet_cache.get(cache_key)
        if cached_ws is not None:
            logger.debug(f"Returning cached worksheet found inside lock for key: {cache_key}")
            return cached_ws
            
        # Fetch worksheet if still not found
        logger.info(f"Worksheet cache miss for key: {cache_key}. Fetching...")
        try:
            client = _get_gspread_client()
            sheet = client.open_by_key(sheet_id)
            worksheet = sheet.worksheet(worksheet_name)
            # Store in cache
            _worksheet_cache[cache_key] = worksheet
            logger.info(f"Successfully fetched and cached worksheet for key: {cache_key}")
            return worksheet
        except APIError as e:
            logger.error(f"API Error accessing sheet '{sheet_id}', worksheet '{worksheet_name}': {e}", exc_info=True)
            if e.response.status_code == 403:
                 logger.error("Permission denied. Ensure the service account email has editor access to the sheet.")
            return None
        except WorksheetNotFound:
            logger.error(f"Worksheet named '{worksheet_name}' not found in Google Sheet ID '{sheet_id}'.")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting worksheet '{sheet_id}/{worksheet_name}': {e}", exc_info=True)
            return None

def format_date_for_sheet(dt_obj: datetime) -> str:
    """Formats a date object into the string format used in the sheet (e.g., 'Jul 16')."""
    return dt_obj.strftime('%b %d')

def find_row_by_date(sheet_id: str, worksheet_name: str, target_dt: datetime, bot_token: str) -> int | None:
    """Finds the row index for a given date in the worksheet.
    Returns 0-based row index if found, None if not found."""
    try:
        worksheet = _get_worksheet(sheet_id, worksheet_name)
        if not worksheet: return None # Added early exit

        target_date = format_date_for_sheet(target_dt)

        # Get the bot's specific configuration
        config = get_config()
        bot_config = config.get_bot_config_by_token(bot_token)
        if not bot_config:
            logger.error(f"Could not find config for bot {bot_token[:6]}... in find_row_by_date")
            return None
        column_map = bot_config['column_map']
        first_data_row = bot_config['first_data_row']
        date_col_idx = column_map.get('DATE_COL_IDX')
        if date_col_idx is None:
             logger.error(f"Schema Error: DATE_COL_IDX not found in map for bot {bot_token[:6]}...")
             return None

        # Get the date column values, starting from first_data_row
        # We only need to fetch up to the last row with data
        last_row = worksheet.row_count
        if last_row <= first_data_row:
            logger.debug(f"No data rows found in worksheet (last_row: {last_row}, first_data_row: {first_data_row})")
            return None

        # Fetch only the date column values from first_data_row to last_row
        date_range = f"{gspread.utils.rowcol_to_a1(first_data_row + 1, date_col_idx + 1)}:{gspread.utils.rowcol_to_a1(last_row, date_col_idx + 1)}"
        date_values = worksheet.get(date_range)

        # Search for the target date in the fetched values
        for i, row in enumerate(date_values):
            # Skip empty cells
            if not row or not row[0]:
                continue

            # Compare the date value
            if row[0] == target_date:
                # Convert to 0-based index and add first_data_row offset
                return i + first_data_row

        logger.debug(f"Date {target_date} not found in worksheet")
        return None

    except Exception as e:
        logger.error(f"Error finding row for date {target_dt}: {e}", exc_info=True) # Added exc_info
        return None

def ensure_date_row(sheet_id: str, worksheet_name: str, target_dt: datetime, bot_token: str) -> int | None:
    """Finds or creates a row for the given date.
    Returns 0-based row index if successful, None if failed."""
    try:
        worksheet = _get_worksheet(sheet_id, worksheet_name)
        if not worksheet: return None # Added early exit

        target_date = format_date_for_sheet(target_dt)

        # Get the bot's specific configuration
        config = get_config()
        bot_config = config.get_bot_config_by_token(bot_token)
        if not bot_config:
            logger.error(f"Could not find config for bot {bot_token[:6]}... in ensure_date_row")
            return None
        column_map = bot_config['column_map']
        first_data_row = bot_config['first_data_row']
        date_col_idx = column_map.get('DATE_COL_IDX')
        if date_col_idx is None:
            logger.error(f"Schema Error: DATE_COL_IDX not found in map for bot {bot_token[:6]}...")
            return None

        # Try to find existing row using the bot_token
        row_idx = find_row_by_date(sheet_id, worksheet_name, target_dt, bot_token)
        if row_idx is not None:
            logger.debug(f"Found existing row {row_idx + 1} for date {target_date}")
            return row_idx

        # If not found, check if the sheet is empty or has no data rows
        last_row = worksheet.row_count
        if last_row <= first_data_row:
            logger.info(f"Sheet is empty or has no data rows. Creating first row for date {target_date}")
            # Create a new row with the date, using None for other cells
            new_row = [None] * len(column_map)  # Use None instead of ""
            new_row[date_col_idx] = target_date
            # Use insert_row instead of append_row to handle potential first_data_row > 0
            # Insert at the correct 1-based index
            worksheet.insert_row(new_row, index=first_data_row + 1, value_input_option='USER_ENTERED')
            logger.info(f"Inserted first data row at index {first_data_row}")
            # Return the 0-based index of the newly created row
            return first_data_row

        # If sheet has rows but no matching date, find the appropriate position to insert
        # Get all dates to determine where to insert the new row
        date_range = f"{gspread.utils.rowcol_to_a1(first_data_row + 1, date_col_idx + 1)}:{gspread.utils.rowcol_to_a1(last_row, date_col_idx + 1)}"
        date_values = worksheet.get(date_range)

        # Find the first date that is later than our target date
        insert_position = first_data_row # Start searching from the first data row
        found_insert_pos = False
        for i, row in enumerate(date_values):
            current_row_index = first_data_row + i # 0-based index of the current row being checked
            if not row or not row[0]:
                continue

            # Compare dates (assuming format is consistent)
            try:
                # Attempt to parse sheet date for comparison if needed, though string comparison might suffice for YYYY-MM-DD
                sheet_date = row[0] # Assuming format_date_for_sheet produces comparable strings
                if sheet_date > target_date:
                    insert_position = current_row_index
                    found_insert_pos = True
                    break
            except Exception as date_comp_err:
                 logger.warning(f"Could not compare date '{row[0]}' with target '{target_date}' at row {current_row_index + 1}. Error: {date_comp_err}")
                 # Decide how to handle comparison errors - maybe insert at end?
                 continue # Skip this row for now

        if not found_insert_pos:
            # If no later date was found, insert after the last row checked
            insert_position = first_data_row + len(date_values)

        # Create a new row with the date, using None for other cells
        new_row = [None] * len(column_map)  # Use None instead of ""
        new_row[date_col_idx] = target_date

        # Insert the row at the determined 0-based position (convert to 1-based for gspread)
        insert_index_1based = insert_position + 1
        logger.debug(f"Inserting new row for date {target_date} at 1-based index {insert_index_1based}")
        # Use insert_rows (plural) which takes a list of rows
        worksheet.insert_rows([new_row], row=insert_index_1based, value_input_option='USER_ENTERED')

        return insert_position # Return the 0-based index where inserted

    except Exception as e:
        logger.error(f"Error ensuring row for date {target_dt}: {e}", exc_info=True)
        return None

def update_metrics(sheet_id: str, worksheet_name: str, target_dt: datetime, metric_updates: dict, bot_token: str) -> bool:
    """Updates one or more metric cells for a given date in the specified sheet/worksheet.
    Args:
        sheet_id: The ID of the Google Sheet.
        worksheet_name: The name of the worksheet within the sheet.
        target_dt: The date object for the row to update.
        metric_updates: A dictionary where keys are 0-based column indices
                        and values are the new values to write.
        bot_token: The token of the bot making the request.
    Returns:
        True if successful, False otherwise.
    """
    if not metric_updates:
        logger.warning("update_metrics called with no updates specified.")
        return True # No update needed is success

    # Pass bot_token to ensure_date_row
    row_index_0based = ensure_date_row(sheet_id, worksheet_name, target_dt, bot_token)
    if row_index_0based is None:
        logger.error(f"Could not find/create row for {format_date_for_sheet(target_dt)} in {sheet_id}/{worksheet_name} to update metrics.")
        return False

    worksheet = _get_worksheet(sheet_id, worksheet_name)
    if not worksheet:
        return False

    updates_for_batch = []
    row_num_1based = row_index_0based + 1

    for col_idx_0based, value in metric_updates.items():
        col_num_1based = col_idx_0based + 1
        cell_a1 = gspread.utils.rowcol_to_a1(row_num_1based, col_num_1based)
        updates_for_batch.append({
            'range': cell_a1,
            'values': [[value]],
        })
        logger.debug(f"Preparing update for cell {cell_a1} in {sheet_id}/{worksheet_name} with value: {value}")

    if updates_for_batch:
        try:
            worksheet.batch_update(updates_for_batch, value_input_option='USER_ENTERED')
            logger.info(f"Successfully updated {len(updates_for_batch)} metric(s) for {format_date_for_sheet(target_dt)} in {sheet_id}/{worksheet_name}.")
            return True
        except Exception as e:
            logger.error(f"Error batch updating metrics for {format_date_for_sheet(target_dt)} in {sheet_id}/{worksheet_name}: {e}", exc_info=True)
            return False
    else:
        logger.info(f"No metric updates prepared for {format_date_for_sheet(target_dt)} in {sheet_id}/{worksheet_name}.")
        return True

def add_nutrition(sheet_id: str, worksheet_name: str, target_dt: datetime, bot_token: str, calories: float = 0, p: float = 0, c: float = 0, f: float = 0, fi: float = 0) -> bool:
    """Adds nutritional values (P, C, F, Fi) to the existing values in the sheet for the target date.
       Leaves the Calories column untouched to allow sheet formulas to calculate it.
    Args:
        sheet_id: The ID of the Google Sheet.
        worksheet_name: The name of the worksheet within the sheet.
        target_dt: The date object for the row to update.
        bot_token: The token of the bot making the request.
        calories: Calories calculated from API (used for reporting but NOT written to sheet).
        p: Protein grams to add.
        c: Carbohydrate grams to add.
        f: Fat grams to add.
        fi: Fiber grams to add.

    Returns:
        True if successful, False otherwise.
    """
    # Get bot config to resolve nutrition column indices
    config = get_config()
    bot_config = config.get_bot_config_by_token(bot_token)
    if not bot_config:
        logger.error(f"Could not find config for bot {bot_token[:6]}... in add_nutrition")
        return False
    column_map = bot_config['column_map']

    # Resolve nutrition indices dynamically
    protein_idx = column_map.get('PROTEIN_COL_IDX')
    carbs_idx = column_map.get('CARBS_COL_IDX')
    fat_idx = column_map.get('FAT_COL_IDX')
    fiber_idx = column_map.get('FIBER_COL_IDX')

    if None in [protein_idx, carbs_idx, fat_idx, fiber_idx]:
        logger.error(f"Schema Error: One or more nutrition columns not found in map for bot {bot_token[:6]}...")
        return False

    # Pass bot_token to ensure_date_row
    row_index_0based = ensure_date_row(sheet_id, worksheet_name, target_dt, bot_token)
    if row_index_0based is None:
        logger.error(f"Could not find or create row for date {format_date_for_sheet(target_dt)} to add nutrition")
        return False

    row_num_1based = row_index_0based + 1
    worksheet = _get_worksheet(sheet_id, worksheet_name)

    # Define columns to update using RESOLVED indices
    cols_to_update = {
        protein_idx: p,
        carbs_idx: c,
        fat_idx: f,
        fiber_idx: fi
    }
    updates = [] # For batch update

    # Only proceed if there are actual P, C, F, or Fi values to add
    if not any(cols_to_update.values()):
        logger.info(f"No non-zero P, C, F, or Fi values to add for {format_date_for_sheet(target_dt)}.")
        # Still return True as no update was needed, but log the calculated calories for info
        if calories > 0:
             logger.info(f"Note: Meal had calculated calories ({calories:.0f}), but only P/C/F/Fi are written to the sheet.")
        return True

    # Determine the range to fetch (Protein to Fiber)
    # Ensure keys exist before calculating min/max if cols_to_update could be empty (though checked above)
    min_col = min(cols_to_update.keys())
    max_col = max(cols_to_update.keys())

    # Fetch existing values in one go if possible
    range_to_fetch = f"{gspread.utils.rowcol_to_a1(row_num_1based, min_col + 1)[0]}{row_num_1based}:{gspread.utils.rowcol_to_a1(row_num_1based, max_col + 1)[0]}{row_num_1based}"
    logger.debug(f"Fetching existing nutrition values from range: {range_to_fetch}")

    try:
        existing_values_list = worksheet.get(range_to_fetch, value_render_option='UNFORMATTED_VALUE')
        existing_row_values = existing_values_list[0] if existing_values_list else []
        logger.debug(f"Existing values fetched: {existing_row_values}")
    except Exception as e:
        logger.error(f"Error fetching existing nutrition values from range {range_to_fetch}: {e}")
        # Fallback to fetching cell by cell if range fetch fails
        existing_row_values = None


    for col_idx_0based, value_to_add in cols_to_update.items():
        # This check might be redundant now due to the `any` check earlier, but safe to keep
        if value_to_add is None or value_to_add == 0:
             continue # Don't add zero values

        col_num_1based = col_idx_0based + 1
        cell_a1 = gspread.utils.rowcol_to_a1(row_num_1based, col_num_1based)
        existing_val = 0.0

        try:
            if existing_row_values is not None:
                # Calculate index within the fetched list (relative to min_col)
                fetch_index = col_idx_0based - min_col
                if 0 <= fetch_index < len(existing_row_values):
                    existing_val_str = str(existing_row_values[fetch_index])
                else:
                    logger.warning(f"Index {fetch_index} out of bounds for fetched range {range_to_fetch}. Fetching cell {cell_a1} individually.")
                    existing_val_str = str(worksheet.cell(row_num_1based, col_num_1based).value)
            else:
                # Fallback: Fetch cell individually if range fetch failed
                existing_val_str = str(worksheet.cell(row_num_1based, col_num_1based).value)

            if existing_val_str and existing_val_str.strip():
                # Remove commas, handle potential non-numeric values gracefully
                cleaned_val_str = existing_val_str.replace(',', '').strip()
                try:
                    existing_val = float(cleaned_val_str)
                except ValueError:
                    logger.warning(f"Non-numeric value '{existing_val_str}' in cell {cell_a1}. Treating as 0.")
                    existing_val = 0.0

            new_value = existing_val + value_to_add
            # Prepare for batch update
            updates.append({
                'range': cell_a1,
                'values': [[new_value]],
            })
            logger.debug(f"Preparing update for cell {cell_a1}: {existing_val} + {value_to_add} = {new_value}")

        except Exception as e:
            logger.error(f"Error processing cell {cell_a1} for nutrition update: {e}")
            return False # Stop if a critical error occurs processing a cell

    if updates:
        try:
            worksheet.batch_update(updates, value_input_option='USER_ENTERED')
            logger.info(f"Successfully added P/C/F/Fi for {format_date_for_sheet(target_dt)}. {len(updates)} cells updated.")
            # Log the calculated calories for user info, even though not written
            if calories > 0:
                logger.info(f"Note: Meal contributed calculated {calories:.0f} calories (based on API lookup). Check sheet formula for final value.")
            return True
        except Exception as e:
            logger.error(f"Error during batch update for nutrition: {e}")
            return False
    else:
        # This case should ideally be caught by the `any` check earlier
        logger.info(f"No non-zero P, C, F, or Fi values were added for {format_date_for_sheet(target_dt)}.")
        return True

def get_data_for_daterange(sheet_id: str, worksheet_name: str, start_dt: datetime.date, end_dt: datetime.date, column_keys: list[str], bot_token: str) -> list[dict]:
    """Fetches data for specified column keys within a date range.

    Args:
        sheet_id: The ID of the Google Sheet.
        worksheet_name: The name of the worksheet.
        start_dt: The start date of the range (inclusive).
        end_dt: The end date of the range (inclusive).
        column_keys: A list of standardized column keys (e.g., ['DATE_COL_IDX', 'CALORIES_COL_IDX']) to fetch.
        bot_token: The token of the bot making the request.

    Returns:
        A list of dictionaries, where each dictionary represents a row
        with keys matching the input column_keys and values from the sheet.
        Returns an empty list if no data is found or an error occurs.
    """
    logger.info(f"Fetching data for keys {column_keys} from {start_dt} to {end_dt}")
    results = []
    try:
        worksheet = _get_worksheet(sheet_id, worksheet_name)
        if not worksheet:
            logger.error("_get_worksheet failed in get_data_for_daterange")
            return []

        # Get bot-specific config
        config = get_config()
        bot_config = config.get_bot_config_by_token(bot_token)
        if not bot_config:
            logger.error(f"Could not find config for bot {bot_token[:6]}... in get_data_for_daterange")
            return []
        column_map = bot_config['column_map']
        first_data_row = bot_config['first_data_row']
        date_col_idx = column_map.get('DATE_COL_IDX')
        if date_col_idx is None:
            logger.error(f"Schema Error: DATE_COL_IDX not found for bot {bot_token[:6]}...")
            return []

        # Resolve column keys to 0-based indices
        col_indices_to_fetch = {}
        for key in column_keys:
            idx = column_map.get(key)
            if idx is None:
                logger.error(f"Schema Error: Column key '{key}' not found for bot {bot_token[:6]}...")
                return [] # Or raise an error / skip the column
            col_indices_to_fetch[key] = idx

        # Fetch all data (consider optimizing if sheet is huge)
        # Getting all data at once is often more efficient than multiple reads
        all_data = worksheet.get_all_values()
        if len(all_data) <= first_data_row:
            logger.info("No data rows found in the sheet.")
            return []

        header_row = all_data[first_data_row -1] # Assuming header is just before data
        data_rows = all_data[first_data_row:]

        # Iterate through data rows
        for i, row in enumerate(data_rows):
            # Check if row has enough columns to contain the date
            if len(row) <= date_col_idx:
                continue # Skip rows that are too short
                
            row_date_str = row[date_col_idx]
            if not row_date_str:
                continue # Skip rows with empty date cell
                
            # Try parsing the date string from the sheet
            try:
                # Attempt common formats, assuming current year if year is missing
                current_year = datetime.now().year
                row_dt = datetime.strptime(f"{row_date_str} {current_year}", '%b %d %Y').date()
            except ValueError:
                 try:
                     # Try parsing with year if it exists
                     row_dt = datetime.strptime(row_date_str, '%b %d, %Y').date()
                 except ValueError:
                     logger.warning(f"Could not parse date '{row_date_str}' in row {first_data_row + i + 1}. Skipping row.")
                     continue # Skip rows with unparseable dates

            # Check if the row date is within the desired range
            if start_dt <= row_dt <= end_dt:
                row_data = {}
                for key, col_idx in col_indices_to_fetch.items():
                    if col_idx < len(row):
                        row_data[key] = row[col_idx]
                    else:
                        row_data[key] = None # Assign None if row is shorter than expected column index
                results.append(row_data)
                
        logger.info(f"Found {len(results)} rows within date range {start_dt} to {end_dt}")
        return results

    except APIError as e:
        logger.error(f"API Error fetching data range: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching data range: {e}", exc_info=True)
        return [] 