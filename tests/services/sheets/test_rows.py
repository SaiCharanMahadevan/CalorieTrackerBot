import unittest
import datetime
from unittest.mock import patch, MagicMock, call
import gspread # Import for exceptions
import requests

# Module to test
from src.services.sheets import rows

# Mock the helper function and potentially find_row_by_date
# Patch target should be where _get_bot_sheet_details is LOOKED UP, which is in rows.py
@patch('src.services.sheets.rows._get_bot_sheet_details') 
class TestSheetsRows(unittest.TestCase):

    def test_find_row_by_date_found(self, mock_get_details):
        """Test finding an existing row by date."""
        mock_ws = MagicMock()
        mock_ws.row_count = 10 # Set row count
        mock_cell = MagicMock()
        mock_cell.row = 5 # gspread cell row is 1-based
        # Setup mock worksheet methods needed by find_row_by_date
        mock_ws.get.return_value = [['Oct 25'], ['Oct 26'], ['Oct 27'], ['Oct 28'], ['Oct 29']]
        # Mock the details helper return value
        mock_column_map = {'DATE_COL_IDX': 0} 
        mock_first_data_row = 1 # 0-based index for first data row
        mock_get_details.return_value = (mock_ws, mock_column_map, mock_first_data_row, "sheet_id", "ws_name")

        sheet_id = "test_sheet_id"
        worksheet_name = "test_ws_name"
        target_dt = datetime.datetime(2023, 10, 27)
        bot_token = "dummy_token"

        result = rows.find_row_by_date(sheet_id, worksheet_name, target_dt, bot_token)

        # Expected row is 3 (0-based index: index 2 in the list + first_data_row 1)
        expected_row_index = 2 + mock_first_data_row
        self.assertEqual(result, expected_row_index)
        mock_get_details.assert_called_once_with(bot_token)
        # Correct assertion: Use mock_ws.row_count for range calculation
        expected_range = f"A{mock_first_data_row + 1}:A{mock_ws.row_count}"
        mock_ws.get.assert_called_once_with(expected_range)

    def test_find_row_by_date_not_found(self, mock_get_details):
        """Test when the date is not found in the sheet."""
        mock_ws = MagicMock()
        mock_ws.row_count = 5 # Set row count
        mock_ws.get.return_value = [['Oct 25'], ['Oct 26']]
        mock_column_map = {'DATE_COL_IDX': 0}
        mock_first_data_row = 0
        mock_get_details.return_value = (mock_ws, mock_column_map, mock_first_data_row, "sheet_id", "ws_name")

        sheet_id = "test_sheet_id"
        worksheet_name = "test_ws_name"
        target_dt = datetime.datetime(2023, 10, 28)
        bot_token = "dummy_token"

        result = rows.find_row_by_date(sheet_id, worksheet_name, target_dt, bot_token)

        self.assertIsNone(result)
        mock_get_details.assert_called_once_with(bot_token)
        expected_range = f"A{mock_first_data_row + 1}:A{mock_ws.row_count}"
        mock_ws.get.assert_called_once_with(expected_range)

    def test_find_row_by_date_details_helper_fails(self, mock_get_details):
        """Test handling when _get_bot_sheet_details returns None."""
        mock_get_details.return_value = None

        sheet_id = "test_sheet_id"
        worksheet_name = "bad_ws_name"
        target_dt = datetime.datetime(2023, 10, 29)
        bot_token = "dummy_token_fails"

        result = rows.find_row_by_date(sheet_id, worksheet_name, target_dt, bot_token)

        self.assertIsNone(result)
        mock_get_details.assert_called_once_with(bot_token)

    def test_find_row_by_date_get_error(self, mock_get_details):
        """Test handling when worksheet.get raises an exception."""
        mock_ws = MagicMock()
        mock_ws.row_count = 10 # Set row count
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500
        mock_ws.get.side_effect = gspread.exceptions.APIError(mock_response)
        mock_column_map = {'DATE_COL_IDX': 0}
        mock_first_data_row = 0
        mock_get_details.return_value = (mock_ws, mock_column_map, mock_first_data_row, "sheet_id", "ws_name")

        sheet_id = "test_sheet_id"
        worksheet_name = "test_ws_name"
        target_dt = datetime.datetime(2023, 10, 30)
        bot_token = "dummy_token"

        result = rows.find_row_by_date(sheet_id, worksheet_name, target_dt, bot_token)

        self.assertIsNone(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_ws.get.assert_called_once() # Check it was called

    # --- Tests for ensure_date_row --- #

    # Patch find_row_by_date used within ensure_date_row
    @patch('src.services.sheets.rows.find_row_by_date')
    def test_ensure_date_row_exists(self, mock_find_row, mock_get_details):
        """Test ensure_date_row when the date row already exists."""
        existing_row_idx = 10
        mock_find_row.return_value = existing_row_idx # find_row returns the index
        mock_ws = MagicMock() # Needed for insert_rows check
        mock_column_map = {'DATE_COL_IDX': 0}
        mock_get_details.return_value = (mock_ws, mock_column_map, 1, "sheet_id", "ws_name")

        sheet_id = "test_sheet_id"
        worksheet_name = "test_ws_name"
        target_dt = datetime.datetime(2023, 11, 1)
        bot_token = "dummy_token"

        result = rows.ensure_date_row(sheet_id, worksheet_name, target_dt, bot_token)

        self.assertEqual(result, existing_row_idx)
        mock_get_details.assert_called_once_with(bot_token)
        mock_find_row.assert_called_once_with(sheet_id, "ws_name", target_dt, bot_token)
        mock_ws.insert_rows.assert_not_called() # Should not insert if row exists

    @patch('src.services.sheets.rows.find_row_by_date')
    def test_ensure_date_row_creates_new(self, mock_find_row, mock_get_details):
        """Test ensure_date_row when the date row needs to be created."""
        mock_find_row.return_value = None # Simulate date not found
        mock_ws = MagicMock()
        mock_ws.row_count = 10 # Set row count
        # Mock getting existing dates for insertion point calculation
        mock_ws.get.return_value = [['Nov 1'], ['Nov 3']]  # FIXED: Use correct format (no leading zero)
        mock_column_map = {'DATE_COL_IDX': 0, 'COL1_IDX': 1} # Need >1 col for row creation size
        mock_first_data_row = 5 # Example start row index
        mock_get_details.return_value = (mock_ws, mock_column_map, mock_first_data_row, "sheet_id", "ws_name")

        sheet_id = "test_sheet_id"
        worksheet_name = "test_ws_name"
        target_dt = datetime.datetime(2023, 11, 2) # Target date Nov 2
        formatted_date = "Nov 2" # FIXED: Use correct format
        bot_token = "dummy_token"

        result = rows.ensure_date_row(sheet_id, worksheet_name, target_dt, bot_token)

        # Should insert between Nov 1 (idx 5) and Nov 3 (idx 6)
        # Expected insertion index (0-based) is 6
        expected_insert_index_0based = 6
        self.assertEqual(result, expected_insert_index_0based)
        mock_get_details.assert_called_once_with(bot_token)
        mock_find_row.assert_called_once_with(sheet_id, "ws_name", target_dt, bot_token)
        expected_get_range = f"A{mock_first_data_row + 1}:A{mock_ws.row_count}"
        mock_ws.get.assert_called_once_with(expected_get_range) # Called to find insertion point
        expected_new_row_data = [None] * len(mock_column_map)
        expected_new_row_data[mock_column_map['DATE_COL_IDX']] = formatted_date
        # gspread insert_rows uses 1-based index
        mock_ws.insert_rows.assert_called_once_with(
            [expected_new_row_data], 
            row=(expected_insert_index_0based + 1),
            value_input_option='USER_ENTERED'
        )

    @patch('src.services.sheets.rows.find_row_by_date')
    def test_ensure_date_row_details_helper_fails(self, mock_find_row, mock_get_details):
        """Test ensure_date_row when _get_bot_sheet_details fails."""
        mock_get_details.return_value = None # Simulate details helper failure

        sheet_id = "test_sheet_id"
        worksheet_name = "bad_ws_name"
        target_dt = datetime.datetime(2023, 11, 3)
        bot_token = "dummy_token_fails"

        result = rows.ensure_date_row(sheet_id, worksheet_name, target_dt, bot_token)

        self.assertIsNone(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_find_row.assert_not_called()

    @patch('src.services.sheets.rows.find_row_by_date')
    def test_ensure_date_row_insert_error(self, mock_find_row, mock_get_details):
        """Test ensure_date_row when insert_rows raises an exception."""
        mock_find_row.return_value = None # Simulate date not found
        mock_ws = MagicMock()
        mock_ws.row_count = 5 # Set row count
        mock_response = MagicMock(spec=requests.Response)
        mock_ws.insert_rows.side_effect = gspread.exceptions.APIError(mock_response)
        mock_ws.get.return_value = [] # No existing dates
        mock_column_map = {'DATE_COL_IDX': 0}
        mock_first_data_row = 0
        mock_get_details.return_value = (mock_ws, mock_column_map, mock_first_data_row, "sheet_id", "ws_name")

        sheet_id = "test_sheet_id"
        worksheet_name = "test_ws_name"
        target_dt = datetime.datetime(2023, 11, 4)
        bot_token = "dummy_token"

        result = rows.ensure_date_row(sheet_id, worksheet_name, target_dt, bot_token)

        self.assertIsNone(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_find_row.assert_called_once_with(sheet_id, "ws_name", target_dt, bot_token)
        mock_ws.insert_rows.assert_called_once() # Check it was called

if __name__ == '__main__':
    unittest.main() 