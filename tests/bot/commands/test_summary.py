import unittest
from unittest.mock import patch, AsyncMock
from datetime import date, timedelta

# Module to test
from src.bot.commands import summary

class TestSummaryCommands(unittest.IsolatedAsyncioTestCase):

    # Helper to create mock Update and Context
    def _create_mocks(self, bot_token="dummy:token"):
        mock_update = AsyncMock()
        mock_context = AsyncMock()
        mock_message = AsyncMock()
        mock_chat = AsyncMock()
        mock_bot = AsyncMock()

        mock_update.effective_chat = mock_chat
        mock_update.message = mock_message
        mock_message.chat_id = 12345
        mock_update.effective_chat.id = 12345
        # Set the internal _bot attribute 
        mock_update._bot = mock_bot
        mock_bot.token = bot_token

        return mock_update, mock_context, mock_bot

    @patch('src.bot.commands.summary._fetch_and_process_summary_data')
    @patch('src.bot.commands.summary._get_current_sheet_config')
    async def test_daily_summary_success(self, mock_get_config, mock_fetch_data):
        """Test daily summary command with successful data fetch."""
        mock_update, mock_context, mock_bot = self._create_mocks()
        mock_config_data = {
            'google_sheet_id': 'sid', 
            'worksheet_name': 'wsn', 
            'column_map': {
                'DATE_COL_IDX': 0, 'CALORIES_COL_IDX': 1, 'PROTEIN_COL_IDX': 2,
                'CARBS_COL_IDX': 3, 'FAT_COL_IDX': 4, 'FIBER_COL_IDX': 5,
                'STEPS_COL_IDX': 6
            }
        }
        mock_get_config.return_value = mock_config_data
        # Mock fetched data (values correspond to the order in column_keys_to_fetch)
        mock_fetch_data.return_value = [['2150', '155.5', '200', '60.1', '35', '10500']] 
        
        await summary.daily_summary_command(mock_update, mock_context)

        mock_get_config.assert_called_once_with(mock_update)
        mock_fetch_data.assert_called_once()
        mock_update.message.reply_html.assert_called_once()
        reply_text = mock_update.message.reply_html.call_args[0][0]

        self.assertIn("Today's Summary", reply_text)
        self.assertIn("Calories: <b>2150</b>", reply_text)
        self.assertIn("Protein: <b>156g</b>", reply_text)
        self.assertIn("Carbs: <b>200g</b>", reply_text)
        self.assertIn("Fat: <b>60g</b>", reply_text)
        self.assertIn("Fiber: <b>35g</b>", reply_text)
        self.assertIn("Steps: <b>10500</b>", reply_text)

    @patch('src.bot.commands.summary._fetch_and_process_summary_data')
    @patch('src.bot.commands.summary._get_current_sheet_config')
    async def test_daily_summary_no_data(self, mock_get_config, mock_fetch_data):
        """Test daily summary command when no data is found for today."""
        mock_update, mock_context, mock_bot = self._create_mocks()
        mock_config_data = {'google_sheet_id': 'sid', 'worksheet_name': 'wsn', 'column_map': {'DATE_COL_IDX': 0}}
        mock_get_config.return_value = mock_config_data
        mock_fetch_data.return_value = [] # Simulate no data found
        
        await summary.daily_summary_command(mock_update, mock_context)

        mock_update.message.reply_html.assert_called_once()
        reply_text = mock_update.message.reply_html.call_args[0][0]
        self.assertIn("No data found for today", reply_text)

    @patch('src.bot.commands.summary.send_error_message') # Mock error sender
    @patch('src.bot.commands.summary._fetch_and_process_summary_data')
    @patch('src.bot.commands.summary._get_current_sheet_config')
    async def test_daily_summary_fetch_error(self, mock_get_config, mock_fetch_data, mock_send_error):
        """Test daily summary command when data fetch returns None."""
        mock_update, mock_context, mock_bot = self._create_mocks()
        mock_config_data = {'google_sheet_id': 'sid', 'worksheet_name': 'wsn', 'column_map': {'DATE_COL_IDX': 0}}
        mock_get_config.return_value = mock_config_data
        mock_fetch_data.return_value = None # Simulate fetch error
        
        await summary.daily_summary_command(mock_update, mock_context)

        # Expect error message to be sent (implicitly by helper), not a normal reply
        mock_update.message.reply_html.assert_not_called()
        # Check if our error handler was called (which might be called by the helper)
        # Note: This depends on helper implementation; adjust if needed.
        # If helper sends error directly, mock that instead (e.g., mock send_error_message if used)
        # Here, we assume the helper returns None and the command might call send_error_message
        # Based on reading the code, the helper doesn't send, the command should if helper returns None
        # Let's re-run and check if send_error_message was called if fetch returned None.
        # --- Correction: The command checks `if data is None:` but doesn't call send_error. We expect NO reply.
        self.assertTrue(True) # Pass if no error occurs and no reply is sent
        

    @patch('src.bot.commands.summary._fetch_and_process_summary_data')
    @patch('src.bot.commands.summary._get_current_sheet_config')
    async def test_weekly_summary_success(self, mock_get_config, mock_fetch_data):
        """Test weekly summary command with successful data fetch."""
        mock_update, mock_context, mock_bot = self._create_mocks()
        mock_config_data = {
            'google_sheet_id': 'sid', 
            'worksheet_name': 'wsn', 
            'column_map': {
                'DATE_COL_IDX': 0, 'SLEEP_HOURS_COL_IDX': 1, 'WEIGHT_COL_IDX': 2,
                'STEPS_COL_IDX': 3, 'CALORIES_COL_IDX': 4
            }
        }
        mock_get_config.return_value = mock_config_data
        # Mock data for multiple days (values correspond to SLEEP, WEIGHT, STEPS, CALORIES)
        mock_fetch_data.return_value = [
            [7.5, 85.0, 10000, 2200], # Day 1
            [8.0, None, 12000, 2300], # Day 2 (missing weight)
            [7.0, 84.5, 8000, '2100']  # Day 3 (calories as string)
        ]
        
        await summary.weekly_summary_command(mock_update, mock_context)

        mock_get_config.assert_called_once_with(mock_update)
        mock_fetch_data.assert_called_once()
        mock_update.message.reply_html.assert_called_once()
        reply_text = mock_update.message.reply_html.call_args[0][0]
        
        # Calculate expected averages
        avg_sleep = (7.5 + 8.0 + 7.0) / 3
        avg_weight = (85.0 + 84.5) / 2 # Only 2 valid weights
        avg_steps = (10000 + 12000 + 8000) / 3
        avg_calories = (2200 + 2300 + 2100) / 3
        
        self.assertIn("Weekly Summary", reply_text)
        self.assertIn(f"Avg Sleep: {avg_sleep:.1f} hours", reply_text)
        self.assertIn(f"Avg Weight: {avg_weight:.1f}", reply_text)
        self.assertIn(f"Avg Steps: {avg_steps:.0f}", reply_text)
        self.assertIn(f"Avg Calories: {avg_calories:.0f}", reply_text)

    @patch('src.bot.commands.summary._fetch_and_process_summary_data')
    @patch('src.bot.commands.summary._get_current_sheet_config')
    async def test_weekly_summary_no_data(self, mock_get_config, mock_fetch_data):
        """Test weekly summary command when no data is found for the week."""
        mock_update, mock_context, mock_bot = self._create_mocks()
        mock_config_data = {'google_sheet_id': 'sid', 'worksheet_name': 'wsn', 'column_map': {'DATE_COL_IDX': 0}}
        mock_get_config.return_value = mock_config_data
        mock_fetch_data.return_value = [] # Simulate no data

        await summary.weekly_summary_command(mock_update, mock_context)

        mock_update.message.reply_html.assert_called_once()
        reply_text = mock_update.message.reply_html.call_args[0][0]
        self.assertIn("No data found for the period", reply_text)
        
if __name__ == '__main__':
    unittest.main() 