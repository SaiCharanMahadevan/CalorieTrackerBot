"""Functions for updating data in Google Sheets (metrics, nutrition)."""

import logging
from datetime import datetime
from typing import Dict
import gspread

# Local imports
from .utils import _get_bot_sheet_details, format_date_for_sheet # Import helper
from .rows import ensure_date_row # Import row management

logger = logging.getLogger(__name__)

def update_metrics(sheet_id: str, worksheet_name: str, target_dt: datetime.date, metric_updates: Dict[int, any], bot_token: str) -> bool:
    """Updates one or more metric cells for a given date.
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

    # Get worksheet and config using the helper
    details = _get_bot_sheet_details(bot_token)
    if not details:
        logger.error(f"Could not get sheet details for bot {bot_token[:6]}... in update_metrics")
        return False
    worksheet, column_map, _, _, _ = details

    # Ensure the row exists for the target date
    row_index_0based = ensure_date_row(sheet_id, worksheet_name, target_dt, bot_token)
    if row_index_0based is None:
        logger.error(f"Could not find/create row for {format_date_for_sheet(target_dt)} in {sheet_id}/{worksheet_name} to update metrics.")
        return False

    updates_for_batch = []
    row_num_1based = row_index_0based + 1

    for col_idx_0based, value in metric_updates.items():
        # Validate that the column index is actually expected by the config
        if col_idx_0based not in column_map.values():
            logger.warning(f"Attempted to update unexpected column index {col_idx_0based}. Skipping.")
            continue
            
        col_num_1based = col_idx_0based + 1
        cell_a1 = gspread.utils.rowcol_to_a1(row_num_1based, col_num_1based)
        updates_for_batch.append({
            'range': cell_a1,
            'values': [[value]],
        })
        logger.debug(f"Preparing update for cell {cell_a1} in {worksheet.title} with value: {value}")

    if updates_for_batch:
        try:
            worksheet.batch_update(updates_for_batch, value_input_option='USER_ENTERED')
            logger.info(f"Successfully updated {len(updates_for_batch)} metric(s) for {format_date_for_sheet(target_dt)} in {worksheet.title}.")
            return True
        except Exception as e:
            logger.error(f"Error batch updating metrics for {format_date_for_sheet(target_dt)} in {worksheet.title}: {e}", exc_info=True)
            return False
    else:
        logger.info(f"No valid metric updates prepared for {format_date_for_sheet(target_dt)} in {worksheet.title}.")
        return True

def add_nutrition(sheet_id: str, worksheet_name: str, target_dt: datetime.date, bot_token: str, calories: float = 0, p: float = 0, c: float = 0, f: float = 0, fi: float = 0) -> bool:
    """Adds nutritional values (P, C, F, Fi) to the existing values in the sheet.
       Leaves the Calories column untouched.
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
    # Get worksheet and config using the helper
    details = _get_bot_sheet_details(bot_token)
    if not details:
        logger.error(f"Could not get sheet details for bot {bot_token[:6]}... in add_nutrition")
        return False
    worksheet, column_map, _, _, _ = details

    # Resolve nutrition indices dynamically
    protein_idx = column_map.get('PROTEIN_COL_IDX')
    carbs_idx = column_map.get('CARBS_COL_IDX')
    fat_idx = column_map.get('FAT_COL_IDX')
    fiber_idx = column_map.get('FIBER_COL_IDX')

    if None in [protein_idx, carbs_idx, fat_idx, fiber_idx]:
        logger.error(f"Schema Error: One or more nutrition columns not found in map for bot {bot_token[:6]}...")
        return False

    # Ensure the row exists
    row_index_0based = ensure_date_row(sheet_id, worksheet_name, target_dt, bot_token)
    if row_index_0based is None:
        logger.error(f"Could not find or create row for date {format_date_for_sheet(target_dt)} to add nutrition")
        return False

    row_num_1based = row_index_0based + 1

    # Define columns to update using RESOLVED indices
    cols_to_update = {
        protein_idx: p,
        carbs_idx: c,
        fat_idx: f,
        fiber_idx: fi
    }
    updates = [] # For batch update

    # Only proceed if there are actual P, C, F, or Fi values to add
    values_to_add = [v for v in cols_to_update.values() if v is not None and v != 0]
    if not values_to_add:
        logger.info(f"No non-zero P, C, F, or Fi values to add for {format_date_for_sheet(target_dt)}.")
        if calories > 0:
             logger.info(f"Note: Meal had calculated calories ({calories:.0f}), but only P/C/F/Fi are written to the sheet.")
        return True

    # Determine the range to fetch (Protein to Fiber)
    valid_indices = [idx for idx, val in cols_to_update.items() if val is not None and val != 0]
    if not valid_indices:
        # Should not happen due to the check above, but as a safeguard
        return True 
        
    min_col = min(valid_indices)
    max_col = max(valid_indices)

    # Fetch existing values in one go
    range_to_fetch_a1 = f"{gspread.utils.rowcol_to_a1(row_num_1based, min_col + 1)[0]}{row_num_1based}:{gspread.utils.rowcol_to_a1(row_num_1based, max_col + 1)[0]}{row_num_1based}"
    logger.debug(f"Fetching existing nutrition values from range: {range_to_fetch_a1}")

    try:
        existing_values_list = worksheet.get(range_to_fetch_a1, value_render_option='UNFORMATTED_VALUE')
        existing_row_values = existing_values_list[0] if existing_values_list else []
        logger.debug(f"Existing values fetched: {existing_row_values}")
    except Exception as e:
        logger.error(f"Error fetching existing nutrition values from range {range_to_fetch_a1}: {e}. Proceeding cell-by-cell.")
        existing_row_values = None # Flag to fetch individually

    for col_idx_0based, value_to_add in cols_to_update.items():
        if value_to_add is None or value_to_add == 0:
             continue

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
                    # This case means the column is outside the fetched range, but we need to update it.
                    # Fetch individually. This might happen if columns aren't contiguous.                    
                    logger.warning(f"Index {fetch_index} out of bounds for fetched range {range_to_fetch_a1}. Fetching cell {cell_a1} individually.")
                    existing_val_str = str(worksheet.cell(row_num_1based, col_num_1based).value)
            else:
                # Fallback: Fetch cell individually if range fetch failed or was skipped
                existing_val_str = str(worksheet.cell(row_num_1based, col_num_1based).value)

            if existing_val_str and existing_val_str.strip() and existing_val_str.lower() != 'none':
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
            if calories > 0:
                logger.info(f"Note: Meal contributed calculated {calories:.0f} calories (based on API lookup). Check sheet formula for final value.")
            return True
        except Exception as e:
            logger.error(f"Error during batch update for nutrition: {e}")
            return False
    else:
        logger.info(f"No valid non-zero P, C, F, or Fi values were prepared for {format_date_for_sheet(target_dt)}.")
        return True 