import unittest
from unittest.mock import patch, MagicMock
import gspread # Import for exceptions
import requests
from datetime import datetime # Import datetime

# Module to test
from src.services.sheets import reader

# Mock the helper functions used within reader.py
@patch('src.services.sheets.reader.find_row_by_date') # Mock find_row used by reader
@patch('src.services.sheets.reader._get_bot_sheet_details') # Mock details helper used by reader
class TestSheetsReader(unittest.TestCase):

    def test_read_data_range_success(self, mock_get_details, mock_find_row):
        """Test successfully reading a data range."""
        mock_ws = MagicMock()
        expected_data = [
            ['76', '2200'] # Example data for the range
        ]
        mock_ws.get.return_value = [expected_data[0]] # worksheet.get returns list of lists
        # Mock the details helper to return the mock worksheet
        mock_get_details.return_value = (mock_ws, {'DATE_COL_IDX': 0}, 2, "sheet_id", "ws_name")
        # Mock find_row_by_date to return a valid row index
        mock_find_row.return_value = 5 # Example 0-based index

        sheet_id = "test_sheet_id" 
        worksheet_name = "metrics_ws"
        target_dt = datetime(2023, 10, 27) # Provide datetime object
        # Example: reading columns 1 and 2 (Weight, Calories)
        start_col_idx = 1
        end_col_idx = 2
        bot_token = "dummy_token"
        # Calculate expected A1 range based on row 6 (index 5 + 1) and cols B, C (idx 1+1, 2+1)
        expected_a1_range = "B6:C6"

        result = reader.read_data_range(sheet_id, worksheet_name, target_dt, start_col_idx, end_col_idx, bot_token)

        self.assertEqual(result, expected_data[0]) # Expect the inner list
        mock_get_details.assert_called_once_with(bot_token)
        mock_find_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        mock_ws.get.assert_called_once_with(expected_a1_range, value_render_option='UNFORMATTED_VALUE')

    def test_read_data_range_empty_result(self, mock_get_details, mock_find_row):
        """Test reading when the sheet range returns an empty list/no values."""
        mock_ws = MagicMock()
        mock_ws.get.return_value = [] # Simulate empty result from .get()
        mock_get_details.return_value = (mock_ws, {'DATE_COL_IDX': 0}, 2, "sheet_id", "ws_name")
        mock_find_row.return_value = 7 # Found the row

        sheet_id = "test_sheet_id"
        worksheet_name = "empty_ws"
        target_dt = datetime(2023, 10, 28)
        start_col_idx = 1
        end_col_idx = 3
        bot_token = "dummy_token"
        expected_a1_range = "B8:D8"
        expected_none_list = [None, None, None] # Based on 3 columns (1 to 3)

        result = reader.read_data_range(sheet_id, worksheet_name, target_dt, start_col_idx, end_col_idx, bot_token)

        self.assertEqual(result, expected_none_list) # Expect list of Nones
        mock_get_details.assert_called_once_with(bot_token)
        mock_find_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        mock_ws.get.assert_called_once_with(expected_a1_range, value_render_option='UNFORMATTED_VALUE')

    def test_read_data_range_details_helper_fails(self, mock_get_details, mock_find_row):
        """Test handling when _get_bot_sheet_details returns None."""
        mock_get_details.return_value = None # Simulate helper failure

        sheet_id = "test_sheet_id"
        worksheet_name = "bad_ws_name" 
        target_dt = datetime(2023, 10, 29)
        start_col_idx = 0 
        end_col_idx = 1
        bot_token = "dummy_token_fails_config"

        result = reader.read_data_range(sheet_id, worksheet_name, target_dt, start_col_idx, end_col_idx, bot_token)

        self.assertIsNone(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_find_row.assert_not_called() # Should fail before finding row

    def test_read_data_range_find_row_fails(self, mock_get_details, mock_find_row):
        """Test handling when find_row_by_date returns None."""
        mock_ws = MagicMock()
        mock_get_details.return_value = (mock_ws, {'DATE_COL_IDX': 0}, 2, "sheet_id", "ws_name")
        mock_find_row.return_value = None # Simulate date not found

        sheet_id = "test_sheet_id"
        worksheet_name = "metrics_ws"
        target_dt = datetime(2023, 10, 30)
        start_col_idx = 1 
        end_col_idx = 2
        bot_token = "dummy_token"

        result = reader.read_data_range(sheet_id, worksheet_name, target_dt, start_col_idx, end_col_idx, bot_token)

        self.assertIsNone(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_find_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        mock_ws.get.assert_not_called() # Should fail before getting range

    def test_read_data_range_get_error(self, mock_get_details, mock_find_row):
        """Test handling when worksheet.get() raises an exception."""
        mock_ws = MagicMock()
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.json.return_value = {"error": {"message": "Read failed"}}
        mock_ws.get.side_effect = gspread.exceptions.APIError(mock_response)
        mock_get_details.return_value = (mock_ws, {'DATE_COL_IDX': 0}, 2, "sheet_id", "ws_name")
        mock_find_row.return_value = 9 # Found the row

        sheet_id = "test_sheet_id"
        worksheet_name = "metrics_ws"
        target_dt = datetime(2023, 10, 31)
        start_col_idx = 1 
        end_col_idx = 1
        bot_token = "dummy_token"
        expected_a1_range = "B10:B10"

        result = reader.read_data_range(sheet_id, worksheet_name, target_dt, start_col_idx, end_col_idx, bot_token)

        self.assertIsNone(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_find_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        mock_ws.get.assert_called_once_with(expected_a1_range, value_render_option='UNFORMATTED_VALUE')

if __name__ == '__main__':
    unittest.main()