"""Utility functions for Google Sheets interactions."""

import logging
from datetime import datetime
from typing import Optional, Tuple, Dict
import gspread

# Project imports
from src.config.config_loader import get_config

# Local imports
from .client import _get_worksheet

logger = logging.getLogger(__name__)


def format_date_for_sheet(dt_obj: datetime.date) -> str:
    """Formats a date object into the string format used in the sheet (e.g., 'Jul 16')."""
    return dt_obj.strftime('%b %d')

def _get_bot_sheet_details(bot_token: str) -> Optional[Tuple[gspread.Worksheet, Dict, int, str, str]]:
    """Fetches bot config and retrieves worksheet, column map, first data row, sheet ID, and worksheet name.
    
    Returns:
        A tuple (worksheet, column_map, first_data_row, sheet_id, worksheet_name) if successful.
        None if config is missing, invalid, or worksheet cannot be accessed.
    """
    config = get_config()
    bot_config = config.get_bot_config_by_token(bot_token)
    if not bot_config:
        logger.error(f"Could not find config for bot {bot_token[:6]}... in _get_bot_sheet_details")
        return None

    sheet_id = bot_config.get('google_sheet_id')
    worksheet_name = bot_config.get('worksheet_name')
    column_map = bot_config.get('column_map')
    first_data_row = bot_config.get('first_data_row')

    if not all([sheet_id, worksheet_name, column_map is not None, first_data_row is not None]):
        logger.error(f"Incomplete configuration for bot {bot_token[:6]}... Missing sheet_id, worksheet_name, column_map, or first_data_row.")
        return None
        
    # Validate essential column indices exist
    if 'DATE_COL_IDX' not in column_map:
         logger.error(f"Schema Error: DATE_COL_IDX not found in map for bot {bot_token[:6]}...")
         return None

    worksheet = _get_worksheet(sheet_id, worksheet_name)
    if not worksheet:
        logger.error(f"Failed to get worksheet '{worksheet_name}' for bot {bot_token[:6]}...")
        return None

    return worksheet, column_map, first_data_row, sheet_id, worksheet_name 