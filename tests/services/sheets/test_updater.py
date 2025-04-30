import unittest
from unittest.mock import patch, MagicMock, call
import gspread # Import for exceptions
import requests
from datetime import datetime

# Module to test
from src.services.sheets import updater

# Mock the helper functions used within updater.py
@patch('src.services.sheets.updater.ensure_date_row') # Mock ensure_date_row used by updater
@patch('src.services.sheets.updater._get_bot_sheet_details') # Mock details helper used by updater
class TestSheetsUpdater(unittest.TestCase):

    def test_update_metrics_success(self, mock_get_details, mock_ensure_row):
        """Test successful update of metrics."""
        mock_ws = MagicMock()
        mock_column_map = {'DATE_COL_IDX': 0, 'WEIGHT_COL_IDX': 1, 'CALORIES_COL_IDX': 2}
        mock_get_details.return_value = (mock_ws, mock_column_map, 1, "sheet_id", "ws_name")
        # Mock ensure_date_row returning a valid row index
        target_row_idx = 5
        mock_ensure_row.return_value = target_row_idx
        
        sheet_id = "test_sheet_id"
        worksheet_name = "metrics_ws"
        target_dt = datetime(2023, 11, 5)
        # Keys are 0-based column indices
        metrics_updates = {
            mock_column_map['WEIGHT_COL_IDX']: 75.5, 
            mock_column_map['CALORIES_COL_IDX']: 2100
        }
        bot_token = "dummy_token"

        result = updater.update_metrics(sheet_id, worksheet_name, target_dt, metrics_updates, bot_token)

        self.assertTrue(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_ensure_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        
        # Check batch_update call
        expected_batch_updates = [
            {'range': f'B{target_row_idx + 1}', 'values': [[75.5]]}, # Col B = idx 1
            {'range': f'C{target_row_idx + 1}', 'values': [[2100]]} # Col C = idx 2
        ]
        mock_ws.batch_update.assert_called_once_with(expected_batch_updates, value_input_option='USER_ENTERED')

    def test_update_metrics_partial_fail_on_batch(self, mock_get_details, mock_ensure_row):
        """Test updating metrics where batch_update fails."""
        mock_ws = MagicMock()
        mock_column_map = {'DATE_COL_IDX': 0, 'WEIGHT_COL_IDX': 1}
        mock_get_details.return_value = (mock_ws, mock_column_map, 1, "sheet_id", "ws_name")
        target_row_idx = 5
        mock_ensure_row.return_value = target_row_idx
        # Mock batch_update to raise an error
        mock_response = MagicMock(spec=requests.Response)
        mock_ws.batch_update.side_effect = gspread.exceptions.APIError(mock_response)

        sheet_id = "test_sheet_id"
        worksheet_name = "metrics_ws"
        target_dt = datetime(2023, 11, 6)
        metrics_updates = { mock_column_map['WEIGHT_COL_IDX']: 75.0 }
        bot_token = "dummy_token"

        result = updater.update_metrics(sheet_id, worksheet_name, target_dt, metrics_updates, bot_token)

        self.assertFalse(result) # Should return False if batch update fails
        mock_get_details.assert_called_once_with(bot_token)
        mock_ensure_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        mock_ws.batch_update.assert_called_once() # Check it was called
        
    def test_update_metrics_ensure_row_fails(self, mock_get_details, mock_ensure_row):
        """Test update metrics when ensure_date_row returns None."""
        mock_ws = MagicMock()
        mock_column_map = {'DATE_COL_IDX': 0, 'WEIGHT_COL_IDX': 1}
        mock_get_details.return_value = (mock_ws, mock_column_map, 1, "sheet_id", "ws_name")
        mock_ensure_row.return_value = None # Simulate ensure_date_row failure

        sheet_id = "test_sheet_id"
        worksheet_name = "metrics_ws"
        target_dt = datetime(2023, 11, 7)
        metrics_updates = { mock_column_map['WEIGHT_COL_IDX']: 75.0 }
        bot_token = "dummy_token"

        result = updater.update_metrics(sheet_id, worksheet_name, target_dt, metrics_updates, bot_token)

        self.assertFalse(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_ensure_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        mock_ws.batch_update.assert_not_called()
        
    def test_update_metrics_details_helper_fails(self, mock_get_details, mock_ensure_row):
        """Test update metrics when _get_bot_sheet_details fails."""
        mock_get_details.return_value = None # Simulate helper failure

        sheet_id = "test_sheet_id"
        worksheet_name = "metrics_ws"
        target_dt = datetime(2023, 11, 8)
        metrics_updates = { 1: 75.0 } # Example index
        bot_token = "dummy_token"

        result = updater.update_metrics(sheet_id, worksheet_name, target_dt, metrics_updates, bot_token)

        self.assertFalse(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_ensure_row.assert_not_called()

    def test_update_metrics_no_updates(self, mock_get_details, mock_ensure_row):
        """Test update metrics called with an empty update dict."""
        sheet_id = "test_sheet_id"
        worksheet_name = "metrics_ws"
        target_dt = datetime(2023, 11, 9)
        metrics_updates = {}
        bot_token = "dummy_token"
        
        result = updater.update_metrics(sheet_id, worksheet_name, target_dt, metrics_updates, bot_token)
        
        self.assertTrue(result) # No updates needed is considered success
        mock_get_details.assert_not_called() # Should exit early
        mock_ensure_row.assert_not_called()

    # --- Tests for add_nutrition --- #

    def test_add_nutrition_success(self, mock_get_details, mock_ensure_row):
        """Test successfully adding nutrition data."""
        mock_ws = MagicMock()
        # Provide a COMPLETE mock column map for nutrition
        mock_column_map = {
            'DATE_COL_IDX': 0,
            'PROTEIN_COL_IDX': 5, 
            'CARBS_COL_IDX': 6, 
            'FAT_COL_IDX': 7, 
            'FIBER_COL_IDX': 8,
            # Include other potential keys if needed by the function
            'CALORIES_API_COL_IDX': 9, # Example, check updater.py if needed
            'CALORIES_FORMULA_COL_IDX': 10 # Example
        }
        mock_get_details.return_value = (mock_ws, mock_column_map, 1, "sheet_id", "ws_name")
        target_row_idx = 10
        mock_ensure_row.return_value = target_row_idx
        mock_ws.get.return_value = [[10.0, 20.0, 5.0, 1.0]] 
        
        sheet_id = "test_sheet_id"
        worksheet_name = "nutrition_ws"
        target_dt = datetime(2023, 11, 10)
        bot_token = "dummy_token"
        calories, p, c, f, fi = 500.0, 15.5, 30.0, 10.2, 2.5

        result = updater.add_nutrition(sheet_id, worksheet_name, target_dt, bot_token, calories, p, c, f, fi)

        self.assertTrue(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_ensure_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        expected_get_range = f"F{target_row_idx + 1}:I{target_row_idx + 1}"
        mock_ws.get.assert_called_once_with(expected_get_range, value_render_option='UNFORMATTED_VALUE')
        expected_batch_updates = [
            {'range': f'F{target_row_idx + 1}', 'values': [[10.0 + p]]}, 
            {'range': f'G{target_row_idx + 1}', 'values': [[20.0 + c]]}, 
            {'range': f'H{target_row_idx + 1}', 'values': [[5.0 + f]]},  
            {'range': f'I{target_row_idx + 1}', 'values': [[1.0 + fi]]}  
        ]
        mock_ws.batch_update.assert_called_once_with(expected_batch_updates, value_input_option='USER_ENTERED')

    def test_add_nutrition_ensure_row_fails(self, mock_get_details, mock_ensure_row):
        """Test add_nutrition when ensure_date_row fails."""
        mock_ws = MagicMock()
        # Provide a COMPLETE mock column map
        mock_column_map = {
            'DATE_COL_IDX': 0, 'PROTEIN_COL_IDX': 1, 'CARBS_COL_IDX': 2, 
            'FAT_COL_IDX': 3, 'FIBER_COL_IDX': 4
        }
        mock_get_details.return_value = (mock_ws, mock_column_map, 1, "sheet_id", "ws_name")
        mock_ensure_row.return_value = None # Simulate failure

        sheet_id = "test_sheet_id"
        worksheet_name = "nutrition_ws"
        target_dt = datetime(2023, 11, 11)
        bot_token = "dummy_token"

        result = updater.add_nutrition(sheet_id, worksheet_name, target_dt, bot_token, p=10)

        self.assertFalse(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_ensure_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        mock_ws.get.assert_not_called()
        mock_ws.batch_update.assert_not_called()
        
    def test_add_nutrition_details_helper_fails(self, mock_get_details, mock_ensure_row):
        """Test add_nutrition when _get_bot_sheet_details fails."""
        mock_get_details.return_value = None # Simulate failure

        sheet_id = "test_sheet_id"
        worksheet_name = "nutrition_ws"
        target_dt = datetime(2023, 11, 12)
        bot_token = "dummy_token"

        result = updater.add_nutrition(sheet_id, worksheet_name, target_dt, bot_token, p=10)

        self.assertFalse(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_ensure_row.assert_not_called()
        
    def test_add_nutrition_no_values_to_add(self, mock_get_details, mock_ensure_row):
        """Test add_nutrition when all P, C, F, Fi values are zero or None."""
        mock_ws = MagicMock()
        # Provide a COMPLETE mock column map
        mock_column_map = {
            'DATE_COL_IDX': 0, 'PROTEIN_COL_IDX': 1, 'CARBS_COL_IDX': 2, 
            'FAT_COL_IDX': 3, 'FIBER_COL_IDX': 4
        }
        mock_get_details.return_value = (mock_ws, mock_column_map, 1, "sheet_id", "ws_name")
        mock_ensure_row.return_value = 5 

        sheet_id = "test_sheet_id"
        worksheet_name = "nutrition_ws"
        target_dt = datetime(2023, 11, 13)
        bot_token = "dummy_token"

        result = updater.add_nutrition(sheet_id, worksheet_name, target_dt, bot_token, p=0, c=0, f=0, fi=0)

        self.assertTrue(result) # No update needed is success
        mock_get_details.assert_called_once_with(bot_token)
        mock_ensure_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        mock_ws.get.assert_not_called() 
        mock_ws.batch_update.assert_not_called()

    def test_add_nutrition_batch_update_fails(self, mock_get_details, mock_ensure_row):
        """Test add_nutrition when the final batch_update fails."""
        mock_ws = MagicMock()
        # Provide a COMPLETE mock column map
        mock_column_map = {
            'DATE_COL_IDX': 0, 'PROTEIN_COL_IDX': 1, 'CARBS_COL_IDX': 2, 
            'FAT_COL_IDX': 3, 'FIBER_COL_IDX': 4
        }
        mock_get_details.return_value = (mock_ws, mock_column_map, 1, "sheet_id", "ws_name")
        target_row_idx = 5
        mock_ensure_row.return_value = target_row_idx
        mock_ws.get.return_value = [[10.0]] # Existing protein (index 1)
        mock_response = MagicMock(spec=requests.Response)
        mock_ws.batch_update.side_effect = gspread.exceptions.APIError(mock_response)

        sheet_id = "test_sheet_id"
        worksheet_name = "nutrition_ws"
        target_dt = datetime(2023, 11, 14)
        bot_token = "dummy_token"

        result = updater.add_nutrition(sheet_id, worksheet_name, target_dt, bot_token, p=10)

        self.assertFalse(result)
        mock_get_details.assert_called_once_with(bot_token)
        mock_ensure_row.assert_called_once_with(sheet_id, worksheet_name, target_dt, bot_token)
        # Check get range based on min/max relevant indices (just Protein=1 here)
        expected_get_range = f"B{target_row_idx + 1}:B{target_row_idx + 1}"
        mock_ws.get.assert_called_once_with(expected_get_range, value_render_option='UNFORMATTED_VALUE') 
        mock_ws.batch_update.assert_called_once() # Check it was called

if __name__ == '__main__':
    unittest.main() 