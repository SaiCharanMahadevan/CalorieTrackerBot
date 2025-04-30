"""Functions for finding and managing rows in Google Sheets."""

import logging
from datetime import datetime
from typing import Optional
import gspread

# Local imports
from .utils import format_date_for_sheet, _get_bot_sheet_details

logger = logging.getLogger(__name__)


def find_row_by_date(sheet_id: str, worksheet_name: str, target_dt: datetime.date, bot_token: str) -> int | None:
    """Finds the 0-based row index for a given date in the worksheet.
       Uses the bot_token to get the correct worksheet and configuration.
    """
    details = _get_bot_sheet_details(bot_token)
    if not details:
        return None
    worksheet, column_map, first_data_row, _, _ = details
    date_col_idx = column_map['DATE_COL_IDX'] # Already validated in helper

    try:
        target_date_str = format_date_for_sheet(target_dt)

        # Get the date column values, starting from first_data_row
        last_row = worksheet.row_count
        if last_row < first_data_row + 1: # Check if there are any data rows at all
            logger.debug(f"No data rows found in worksheet (last_row: {last_row}, first_data_row: {first_data_row})")
            return None

        # Fetch only the date column values from first_data_row to last_row
        # +1 for indices because gspread uses 1-based indexing
        date_range_a1 = f"{gspread.utils.rowcol_to_a1(first_data_row + 1, date_col_idx + 1)[0]}{first_data_row + 1}:{gspread.utils.rowcol_to_a1(last_row, date_col_idx + 1)[0]}{last_row}"
        logger.debug(f"Fetching date column range: {date_range_a1}")
        date_values = worksheet.get(date_range_a1)

        # Search for the target date in the fetched values
        for i, row_list in enumerate(date_values):
            # Skip empty cells/rows
            if not row_list or not row_list[0]:
                continue
            
            # Compare the date value
            if row_list[0] == target_date_str:
                # Convert list index `i` back to 0-based sheet row index
                found_row_idx = i + first_data_row
                logger.debug(f"Date {target_date_str} found at 0-based row index {found_row_idx}")
                return found_row_idx

        logger.debug(f"Date {target_date_str} not found in worksheet")
        return None

    except Exception as e:
        logger.error(f"Error finding row for date {target_dt}: {e}", exc_info=True)
        return None

def ensure_date_row(sheet_id: str, worksheet_name: str, target_dt: datetime.date, bot_token: str) -> int | None:
    """Finds or creates a row for the given date.
       Returns 0-based row index if successful, None if failed.
    """
    details = _get_bot_sheet_details(bot_token)
    if not details:
        return None
    worksheet, column_map, first_data_row, _, ws_name_from_details = details
    # Use sheet_id and ws_name_from_details for consistency, although they might match input args
    date_col_idx = column_map['DATE_COL_IDX']

    try:
        target_date_str = format_date_for_sheet(target_dt)

        # Try to find existing row using the bot_token
        row_idx = find_row_by_date(sheet_id, ws_name_from_details, target_dt, bot_token)
        if row_idx is not None:
            logger.debug(f"Found existing row {row_idx + 1} for date {target_date_str}")
            return row_idx

        # If not found, determine where to insert
        last_row = worksheet.row_count
        insert_position = first_data_row # Default: insert at the first data row position
        found_insert_pos = False
        
        # Only fetch existing dates if there are data rows to check
        if last_row >= first_data_row + 1:
            # Get all dates to determine where to insert the new row
            # +1 for indices because gspread uses 1-based indexing
            date_range_a1 = f"{gspread.utils.rowcol_to_a1(first_data_row + 1, date_col_idx + 1)[0]}{first_data_row + 1}:{gspread.utils.rowcol_to_a1(last_row, date_col_idx + 1)[0]}{last_row}"
            logger.debug(f"Fetching date column range for insertion check: {date_range_a1}")
            date_values = worksheet.get(date_range_a1)

            # Find the first date that is later than our target date
            for i, row_list in enumerate(date_values):
                current_row_index = first_data_row + i # 0-based index
                if not row_list or not row_list[0]:
                    continue
                try:
                    sheet_date_str = row_list[0]
                    # Simple string comparison assuming 'Mmm dd' format works chronologically within a year
                    # TODO: Improve date comparison robustness if跨年 dates or different formats exist
                    if sheet_date_str > target_date_str:
                        insert_position = current_row_index
                        found_insert_pos = True
                        break
                except Exception as date_comp_err:
                     logger.warning(f"Could not compare date '{row_list[0]}' with target '{target_date_str}' at row {current_row_index + 1}. Error: {date_comp_err}")
                     continue
            
            if not found_insert_pos:
                # If no later date was found, insert after the last valid data row examined
                insert_position = first_data_row + len(date_values)
        
        # Create a new row with the date, using None for other cells
        num_columns = len(column_map) # Determine expected number of columns from map
        new_row = [None] * num_columns
        new_row[date_col_idx] = target_date_str

        # Insert the row at the determined 0-based position (convert to 1-based for gspread)
        insert_index_1based = insert_position + 1
        logger.debug(f"Inserting new row for date {target_date_str} at 1-based index {insert_index_1based}")
        # Use insert_rows (plural) which takes a list of rows
        worksheet.insert_rows([new_row], row=insert_index_1based, value_input_option='USER_ENTERED')

        return insert_position # Return the 0-based index where inserted

    except Exception as e:
        logger.error(f"Error ensuring row for date {target_dt}: {e}", exc_info=True)
        return None 