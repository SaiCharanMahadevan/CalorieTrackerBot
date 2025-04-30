"""Functions for reading data from Google Sheets."""

import logging
from datetime import datetime
from typing import Optional, List, Any
import gspread

# Local imports
from .utils import _get_bot_sheet_details, format_date_for_sheet # Import helper
from .rows import find_row_by_date # Import row finding

logger = logging.getLogger(__name__)

def read_data_range(sheet_id: str, worksheet_name: str, target_dt: datetime.date, start_col_idx: int, end_col_idx: int, bot_token: str) -> Optional[List[Any]]:
    """Reads a horizontal range of cells for a specific date.
    Args:
        sheet_id: The ID of the Google Sheet.
        worksheet_name: The name of the worksheet within the sheet.
        target_dt: The date object for the row to read.
        start_col_idx: The starting 0-based column index of the range.
        end_col_idx: The ending 0-based column index of the range (inclusive).
        bot_token: The token of the bot making the request.

    Returns:
        A list of values from the specified range for the target date's row,
        or None if the row isn't found or an error occurs.
    """
    # Get worksheet and config using the helper
    details = _get_bot_sheet_details(bot_token)
    if not details:
        logger.error(f"Could not get sheet details for bot {bot_token[:6]}... in read_data_range")
        return None
    worksheet, _, _, _, _ = details # Don't need column_map etc. here, just the worksheet

    # Find the row for the target date
    row_index_0based = find_row_by_date(sheet_id, worksheet_name, target_dt, bot_token)
    if row_index_0based is None:
        logger.warning(f"Could not find row for {format_date_for_sheet(target_dt)} in {sheet_id}/{worksheet_name} to read data range.")
        return None # Return None if date row doesn't exist

    row_num_1based = row_index_0based + 1
    start_col_1based = start_col_idx + 1
    end_col_1based = end_col_idx + 1

    if start_col_1based > end_col_1based:
         logger.error(f"Invalid column range requested: start ({start_col_idx}) > end ({end_col_idx})")
         return None

    try:
        # Construct A1 notation for the range
        start_cell_a1 = gspread.utils.rowcol_to_a1(row_num_1based, start_col_1based)
        end_cell_a1 = gspread.utils.rowcol_to_a1(row_num_1based, end_col_1based)
        range_a1 = f"{start_cell_a1}:{end_cell_a1}"

        logger.debug(f"Reading data from range: {range_a1} in {worksheet.title}")
        # Fetch the values, preserving formatting (e.g., dates as strings)
        # Use UNFORMATTED_VALUE for numbers, FORMATTED_VALUE for dates/text? Check gspread docs.
        # Let's try UNFORMATTED_VALUE first for consistency with writes.
        values = worksheet.get(range_a1, value_render_option='UNFORMATTED_VALUE')

        if values:
            # values is a list of lists, e.g., [[val1, val2, val3]]
            logger.debug(f"Successfully read values from {range_a1}: {values[0]}")
            return values[0] # Return the inner list
        else:
            # Range exists but might be empty
            logger.debug(f"Range {range_a1} found but contained no values.")
            # Return a list of Nones matching the expected range size
            num_cells = end_col_idx - start_col_idx + 1
            return [None] * num_cells

    except gspread.exceptions.APIError as e:
         logger.error(f"API error reading range {range_a1} for date {format_date_for_sheet(target_dt)}: {e}", exc_info=True)
         return None
    except Exception as e:
        logger.error(f"Unexpected error reading range {range_a1} for date {format_date_for_sheet(target_dt)}: {e}", exc_info=True)
        return None 