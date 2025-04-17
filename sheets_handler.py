"""Handles interactions with the Google Sheet."""

import gspread
import logging
from datetime import date
from google.oauth2.service_account import Credentials

import config

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

_worksheet = None

def _get_worksheet():
    """Authenticates and returns the gspread Worksheet object."""
    global _worksheet
    if _worksheet is None:
        try:
            creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=config.SCOPES)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(config.GOOGLE_SHEET_ID)
            _worksheet = sheet.worksheet(config.WORKSHEET_NAME)
            logger.info(f"Successfully connected to Google Sheet: {config.GOOGLE_SHEET_ID}, Worksheet: {config.WORKSHEET_NAME}")
        except FileNotFoundError:
            logger.error(f"Service account file not found at: {config.SERVICE_ACCOUNT_FILE}. Please check the path.")
            raise
        except Exception as e:
            logger.error(f"Error connecting to Google Sheets: {e}")
            raise
    return _worksheet

def format_date_for_sheet(dt_obj: date) -> str:
    """Formats a date object into the string format used in the sheet (e.g., 'Jul 16')."""
    # Adjust format '%b %d' if your sheet uses a different date format in Column B
    return dt_obj.strftime('%b %d')

def find_row_by_date(target_dt: date) -> int | None:
    """Finds the row index (0-based) for a given date in the sheet.

    Args:
        target_dt: The date object to search for.

    Returns:
        The 0-based row index if found, otherwise None.
    """
    target_date_str = format_date_for_sheet(target_dt)
    logger.info(f"Searching for date string: {target_date_str}")
    try:
        worksheet = _get_worksheet()
        # Get all date values starting from the actual data rows (Column B)
        # Adding +1 to column index because gspread is 1-indexed for col_values
        date_col_values = worksheet.col_values(config.DATE_COL_IDX + 1)

        # Search only within the data rows
        data_rows_values = date_col_values[config.FIRST_DATA_ROW_IDX:]

        # Find the index within this slice
        relative_index = data_rows_values.index(target_date_str)
        # Add the offset of the starting row to get the absolute 0-based index
        absolute_index = config.FIRST_DATA_ROW_IDX + relative_index
        logger.info(f"Found date '{target_date_str}' at row index: {absolute_index}")
        return absolute_index
    except ValueError:
        logger.info(f"Date string '{target_date_str}' not found in column {config.DATE_COL_IDX + 1}.")
        return None
    except Exception as e:
        logger.error(f"Error reading date column {config.DATE_COL_IDX + 1}: {e}")
        return None

def ensure_date_row(target_dt: date) -> int | None:
    """Finds row index (0-based) for a date, creates the row if it doesn't exist.

    Args:
        target_dt: The date object.

    Returns:
        The 0-based row index of the existing or newly created row, or None on error.
    """
    row_index_0based = find_row_by_date(target_dt)
    if row_index_0based is None:
        # Define target_date_str *before* the try block to ensure it exists in except scope
        target_date_str = format_date_for_sheet(target_dt)
        logger.info(f"Date {target_date_str} not found. Appending new row.")
        try:
            worksheet = _get_worksheet()
            # Create a list representing the row, padding with empty strings
            num_cols = worksheet.col_count
            new_row_data = [''] * num_cols
            # Add 1 to DATE_COL_IDX because new_row_data is 0-indexed like Python lists
            new_row_data[config.DATE_COL_IDX] = target_date_str
            worksheet.append_row(new_row_data, value_input_option='USER_ENTERED')
            # Find the newly added row (it will be the last one)
            new_row_index = worksheet.row_count - 1 # worksheet.row_count is 1-based index of last row
            logger.info(f"Appended new row for date: {target_date_str} at index {new_row_index}")
            return new_row_index
        except Exception as e:
            # target_date_str is now guaranteed to be defined here
            logger.error(f"Error appending new row for date {target_date_str}: {e}")
            return None
    else:
        return row_index_0based

def update_metric(target_dt: date, metric_name: str, value) -> bool:
    """Updates a single non-nutritional metric for a given date.

    Args:
        target_dt: The date object for the row to update.
        metric_name: The user-friendly name of the metric (e.g., 'weight', 'sleep').
        value: The new value to write to the cell.

    Returns:
        True if successful, False otherwise.
    """
    metric_name_lower = metric_name.lower()
    if metric_name_lower not in config.METRIC_COLUMN_MAP:
        logger.warning(f"Unknown metric name: {metric_name}")
        return False

    col_index_0based = config.METRIC_COLUMN_MAP[metric_name_lower]
    row_index_0based = ensure_date_row(target_dt)

    if row_index_0based is None:
        logger.error(f"Could not find or create row for date {format_date_for_sheet(target_dt)} to update metric {metric_name}")
        return False

    try:
        worksheet = _get_worksheet()
        # gspread uses 1-based indexing for rows and columns
        row_num_1based = row_index_0based + 1
        col_num_1based = col_index_0based + 1
        worksheet.update_cell(row_num_1based, col_num_1based, value)
        logger.info(f"Updated metric '{metric_name}' to '{value}' for date {format_date_for_sheet(target_dt)} at cell {gspread.utils.rowcol_to_a1(row_num_1based, col_num_1based)}")
        return True
    except Exception as e:
        logger.error(f"Error updating cell ({row_index_0based + 1}, {col_index_0based + 1}) for metric {metric_name}: {e}")
        return False

def add_nutrition(target_dt: date, calories: float = 0, p: float = 0, c: float = 0, f: float = 0, fi: float = 0) -> bool:
    """Adds nutritional values (P, C, F, Fi) to the existing values in the sheet for the target date.
       Leaves the Calories column untouched to allow sheet formulas to calculate it.

    Args:
        target_dt: The date object for the row to update.
        calories: Calories calculated from API (used for reporting but NOT written to sheet).
        p: Protein grams to add.
        c: Carbohydrate grams to add.
        f: Fat grams to add.
        fi: Fiber grams to add.

    Returns:
        True if successful, False otherwise.
    """
    row_index_0based = ensure_date_row(target_dt)
    if row_index_0based is None:
        logger.error(f"Could not find or create row for date {format_date_for_sheet(target_dt)} to add nutrition")
        return False

    row_num_1based = row_index_0based + 1
    worksheet = _get_worksheet()

    # Define columns to update - EXCLUDE CALORIES_COL_IDX
    cols_to_update = {
        # config.CALORIES_COL_IDX: calories, # Excluded: Let sheet formula calculate
        config.PROTEIN_COL_IDX: p,
        config.CARBS_COL_IDX: c,
        config.FAT_COL_IDX: f,
        config.FIBER_COL_IDX: fi
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