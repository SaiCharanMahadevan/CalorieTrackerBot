"""Module for interacting with Google Sheets.

Provides functions to:
- Find or create rows based on dates.
- Update metric values.
- Add nutrition data.
- Read data ranges.
"""

# Public API for the sheets service

from .utils import format_date_for_sheet
from .rows import find_row_by_date, ensure_date_row
from .updater import update_metrics, add_nutrition
from .reader import read_data_range

__all__ = [
    'format_date_for_sheet',
    'find_row_by_date',
    'ensure_date_row',
    'update_metrics',
    'add_nutrition',
    'read_data_range',
] 