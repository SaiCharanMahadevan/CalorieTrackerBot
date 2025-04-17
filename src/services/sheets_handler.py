"""Handles interactions with Google Sheets for storing user data."""

import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from src.config.config import PROTEIN_COL_IDX, CARBS_COL_IDX, FAT_COL_IDX, FIBER_COL_IDX, SCOPES, DATE_COL_IDX, FIRST_DATA_ROW_IDX
from src.config.config_loader import get_config
import gspread
from google.oauth2 import service_account
import threading

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
        except gspread.exceptions.APIError as e:
            logger.error(f"gspread API Error accessing sheet '{sheet_id}', worksheet '{worksheet_name}': {e}", exc_info=True)
            if e.response.status_code == 403:
                 logger.error("Permission denied. Ensure the service account email has editor access to the sheet.")
            return None
        except gspread.exceptions.WorksheetNotFound:
            logger.error(f"Worksheet named '{worksheet_name}' not found in Google Sheet ID '{sheet_id}'.")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting worksheet '{sheet_id}/{worksheet_name}': {e}", exc_info=True)
            return None

def format_date_for_sheet(dt_obj: datetime) -> str:
    """Formats a date object into the string format used in the sheet (e.g., 'Jul 16')."""
    return dt_obj.strftime('%b %d')

def find_row_by_date(sheet_id: str, worksheet_name: str, target_dt: datetime) -> int | None:
    """Finds the row index (0-based) for a given date in the specified sheet/worksheet.
    Args:
        sheet_id: The ID of the Google Sheet.
        worksheet_name: The name of the worksheet within the sheet.
        target_dt: The date object to search for.
    Returns:
        The 0-based row index if found, otherwise None.
    """
    worksheet = _get_worksheet(sheet_id, worksheet_name)
    if not worksheet:
        return None

    target_date_str = format_date_for_sheet(target_dt)
    logger.info(f"Searching for date string: {target_date_str} in {sheet_id}/{worksheet_name}")
    try:
        date_col_values = worksheet.col_values(DATE_COL_IDX + 1)
        data_rows_values = date_col_values[FIRST_DATA_ROW_IDX:]
        relative_index = data_rows_values.index(target_date_str)
        absolute_index = FIRST_DATA_ROW_IDX + relative_index
        logger.info(f"Found date '{target_date_str}' at row index: {absolute_index} in {sheet_id}/{worksheet_name}")
        return absolute_index
    except ValueError:
        logger.info(f"Date string '{target_date_str}' not found in column {DATE_COL_IDX + 1} of {sheet_id}/{worksheet_name}.")
        return None
    except Exception as e:
        logger.error(f"Error reading date column {DATE_COL_IDX + 1} from {sheet_id}/{worksheet_name}: {e}")
        return None

def ensure_date_row(sheet_id: str, worksheet_name: str, target_dt: datetime) -> int | None:
    """Finds row index (0-based) for a date, creates the row if it doesn't exist.
    Args:
        sheet_id: The ID of the Google Sheet.
        worksheet_name: The name of the worksheet within the sheet.
        target_dt: The date object.
    Returns:
        The 0-based row index of the existing or newly created row, or None on error.
    """
    row_index_0based = find_row_by_date(sheet_id, worksheet_name, target_dt)
    if row_index_0based is not None:
        return row_index_0based

    # Date not found, try to append
    target_date_str = format_date_for_sheet(target_dt)
    logger.info(f"Date {target_date_str} not found in {sheet_id}/{worksheet_name}. Appending new row.")
    worksheet = _get_worksheet(sheet_id, worksheet_name)
    if not worksheet:
        return None

    try:
        num_cols = worksheet.col_count
        new_row_data = [''] * num_cols
        new_row_data[DATE_COL_IDX] = target_date_str
        worksheet.append_row(new_row_data, value_input_option='USER_ENTERED')
        # Find the newly added row (it will be the last one)
        # Re-fetch row count after append
        new_row_index = worksheet.row_count - 1
        logger.info(f"Appended new row for date: {target_date_str} at index {new_row_index} in {sheet_id}/{worksheet_name}")
        return new_row_index
    except Exception as e:
        logger.error(f"Error appending new row for date {target_date_str} to {sheet_id}/{worksheet_name}: {e}")
        return None

def update_metrics(sheet_id: str, worksheet_name: str, target_dt: datetime, metric_updates: dict) -> bool:
    """Updates one or more metric cells for a given date in the specified sheet/worksheet.
    Args:
        sheet_id: The ID of the Google Sheet.
        worksheet_name: The name of the worksheet within the sheet.
        target_dt: The date object for the row to update.
        metric_updates: A dictionary where keys are 0-based column indices
                        and values are the new values to write.
    Returns:
        True if successful, False otherwise.
    """
    if not metric_updates:
        logger.warning("update_metrics called with no updates specified.")
        return True # No update needed is success

    row_index_0based = ensure_date_row(sheet_id, worksheet_name, target_dt)
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
            logger.error(f"Error batch updating metrics for {format_date_for_sheet(target_dt)} in {sheet_id}/{worksheet_name}: {e}")
            return False
    else:
        logger.info(f"No metric updates prepared for {format_date_for_sheet(target_dt)} in {sheet_id}/{worksheet_name}.")
        return True

def add_nutrition(sheet_id: str, worksheet_name: str, target_dt: datetime, calories: float = 0, p: float = 0, c: float = 0, f: float = 0, fi: float = 0) -> bool:
    """Adds nutritional values (P, C, F, Fi) to the existing values in the sheet for the target date.
       Leaves the Calories column untouched to allow sheet formulas to calculate it.
    Args:
        sheet_id: The ID of the Google Sheet.
        worksheet_name: The name of the worksheet within the sheet.
        target_dt: The date object for the row to update.
        calories: Calories calculated from API (used for reporting but NOT written to sheet).
        p: Protein grams to add.
        c: Carbohydrate grams to add.
        f: Fat grams to add.
        fi: Fiber grams to add.

    Returns:
        True if successful, False otherwise.
    """
    row_index_0based = ensure_date_row(sheet_id, worksheet_name, target_dt)
    if row_index_0based is None:
        logger.error(f"Could not find or create row for date {format_date_for_sheet(target_dt)} to add nutrition")
        return False

    row_num_1based = row_index_0based + 1
    worksheet = _get_worksheet(sheet_id, worksheet_name)

    # Define columns to update - EXCLUDE CALORIES_COL_IDX
    cols_to_update = {
        # config.CALORIES_COL_IDX: calories, # Excluded: Let sheet formula calculate
        PROTEIN_COL_IDX: p,
        CARBS_COL_IDX: c,
        FAT_COL_IDX: f,
        FIBER_COL_IDX: fi
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