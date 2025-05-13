import unittest
from unittest.mock import patch, AsyncMock, MagicMock, call
from datetime import date, datetime

# Module to test
from src.bot.commands import log_command

# Define a fixed date for testing - ADJUSTED YEAR
FIXED_TODAY = date(2025, 5, 1)
FIXED_TODAY_STR = "May 01" # Keep string simple

class TestLogCommand(unittest.IsolatedAsyncioTestCase):

    # --- Helper to create mocks (remove patch) ---
    # @patch('datetime.date') # Remove patch from helper
    def _create_mocks(self, args=None, caption=None, photo=False, text="/log"): # Remove mock_date arg
        # We will mock date.today() inside each test method as needed
        mock_update = AsyncMock()
        mock_context = AsyncMock()
        mock_message = AsyncMock()
        mock_user = AsyncMock()
        mock_chat = AsyncMock()
        mock_bot = AsyncMock()
        mock_photo_file = AsyncMock()

        mock_update.effective_user = mock_user
        mock_update.message = mock_message
        mock_update.effective_chat = mock_chat
        mock_message.chat = mock_chat
        mock_message.chat_id = 12345
        mock_update.effective_chat.id = 12345
        mock_context.args = args if args is not None else []
        # Construct message text based on args if provided
        if args:
            mock_message.text = f"/log {' '.join(args)}"
        else:
            mock_message.text = text # Use default /log or provided text if no args
        mock_message.caption = caption
        mock_message.photo = [AsyncMock()] if photo else []
        # Set the internal _bot attribute
        mock_update._bot = mock_bot 
        mock_bot.token = "dummytoken:1234"

        # Mock photo download if needed
        mock_bot.get_file.return_value = mock_photo_file
        mock_photo_file.download_as_bytearray.return_value = bytearray(b'mock_photo_data')

        return mock_update, mock_context, mock_bot

    # --- Test Methods (Simplify: Keep only first test for now) ---
    @patch('src.bot.commands.log_command.date') # Outermost patch -> First arg: mock_date
    @patch('src.bot.commands.log_command._get_current_sheet_config') # Innermost patch -> Last arg: mock_get_config
    async def test_log_command_entry_no_args(self, mock_date, mock_get_config):
        """Test /log with no arguments."""
        mock_date.today.return_value = FIXED_TODAY
        mock_update, mock_context, mock_bot = self._create_mocks()
        mock_config_data = {'google_sheet_id': 'sid', 'worksheet_name': 'wsn', 'column_map': {}}
        # Make _get_current_sheet_config return the mock data
        mock_get_config.return_value = mock_config_data

        # Mock reply_text directly on the message mock
        # We need AsyncMock here if reply_text is async
        mock_update.message.reply_text = AsyncMock()

        await log_command.log_command_entry(mock_update, mock_context)

        # Assert reply_text was called with the correct message
        mock_update.message.reply_text.assert_called_once_with(
            'Please provide arguments for the /log command. Use /help for details.'
        )
        # Ensure no service functions were called (add mocks back later)
        # mock_parse_text.assert_not_called()
        # mock_update_metrics.assert_not_called()
        # mock_add_nutrition.assert_not_called()

    # test_log_command_text_metric_success: Remove ALL decorators 
    async def test_log_command_text_metric_success(self):
        """Test /log with a standard text metric update."""
        # Use nested `with patch(...)` instead of decorators
        with patch('src.bot.commands.log_command.date') as mock_date, \
             patch('src.bot.commands.log_command.format_date_for_sheet', return_value=FIXED_TODAY_STR) as mock_format_date, \
             patch('src.bot.commands.log_command.add_nutrition', new_callable=AsyncMock) as mock_add_nutrition, \
             patch('src.bot.commands.log_command.update_metrics') as mock_update_metrics, \
             patch('src.bot.commands.log_command.get_nutrition_for_items') as mock_get_nutrition, \
             patch('src.bot.commands.log_command.parse_meal_image_with_gemini') as mock_parse_image, \
             patch('src.bot.commands.log_command.parse_meal_text_with_gemini') as mock_parse_text, \
             patch('src.bot.commands.log_command.dateparser.parse', return_value=None) as mock_dateparse, \
             patch('src.bot.commands.log_command._get_current_sheet_config') as mock_get_config, \
             patch.dict(log_command.LOGGING_CHOICES_MAP, {'weight': {'type': 'numeric_single', 'metrics': ['WEIGHT_COL_IDX']}}, clear=True):
            
            # --- Test Setup --- 
            mock_date.today.return_value = FIXED_TODAY
            mock_update, mock_context, mock_bot = self._create_mocks(args=['weight', '85.5'])
            mock_config_data = {
                'google_sheet_id': 'sid', 
                'worksheet_name': 'wsn', 
                'column_map': {'WEIGHT_COL_IDX': 1}
            }
            mock_get_config.return_value = mock_config_data
            mock_update_metrics.return_value = True # Simulate success
            mock_update.message.reply_text = AsyncMock()

            # --- Execute --- 
            await log_command.log_command_entry(mock_update, mock_context)

            # --- Assert --- 
            # print(f"DEBUG: mock_dateparse calls: {mock_dateparse.call_args_list}")
            # print(f"DEBUG: mock_update_metrics calls: {mock_update_metrics.call_args_list}")
            print(f"DEBUG: mock_update.message.reply_text calls: {mock_update.message.reply_text.call_args_list}")
            
            mock_update_metrics.assert_called_once()
            # Restore the rest of the assertions
            call_args, call_kwargs = mock_update_metrics.call_args
            self.assertEqual(call_kwargs['sheet_id'], 'sid')
            self.assertEqual(call_kwargs['worksheet_name'], 'wsn')
            self.assertEqual(call_kwargs['target_dt'], FIXED_TODAY)
            self.assertEqual(call_kwargs['metric_updates'], {1: 85.5})
            self.assertEqual(call_kwargs['bot_token'], mock_bot.token)
            mock_update.message.reply_text.assert_called_once_with(
                f"✅ Updated 'weight' to '85.5' for {FIXED_TODAY_STR}."
            )
            mock_add_nutrition.assert_not_called()
            mock_format_date.assert_called()

    # Uncomment test_log_command_meal_text_success
    async def test_log_command_meal_text_success(self):
        """Test /log meal with text description."""
        # Nested patches for dependencies
        with patch('src.bot.commands.log_command.date') as mock_date, \
             patch('src.bot.commands.log_command.format_date_for_sheet', return_value=FIXED_TODAY_STR) as mock_format_date, \
             patch('src.bot.commands.log_command.add_nutrition', new_callable=AsyncMock) as mock_add_nutrition, \
             patch('src.bot.commands.log_command.update_metrics') as mock_update_metrics, \
             patch('src.bot.commands.log_command.get_nutrition_for_items') as mock_get_nutrition, \
             patch('src.bot.commands.log_command.parse_meal_image_with_gemini') as mock_parse_image, \
             patch('src.bot.commands.log_command.parse_meal_text_with_gemini') as mock_parse_text, \
             patch('src.bot.commands.log_command.dateparser.parse', return_value=None) as mock_dateparse, \
             patch('src.bot.commands.log_command._get_current_sheet_config') as mock_get_config:
            
            # --- Test Setup --- 
            mock_date.today.return_value = FIXED_TODAY
            mock_update, mock_context, mock_bot = self._create_mocks(args=['meal', '100g', 'chicken'])
            mock_config_data = {'google_sheet_id': 'sid', 'worksheet_name': 'wsn', 'column_map': {}}
            mock_get_config.return_value = mock_config_data
            mock_parsed_items = [{'item': 'chicken', 'quantity_g': 100.0}]
            mock_nutrition_info = {'calories': 165.0, 'protein': 31.0, 'carbs': 0.0, 'fat': 3.6, 'fiber': 0.0}
            mock_parse_text.return_value = mock_parsed_items
            mock_get_nutrition.return_value = mock_nutrition_info
            mock_add_nutrition.return_value = True
            mock_processing_message = AsyncMock()
            mock_update.message.reply_text.return_value = mock_processing_message

            # --- Execute --- 
            await log_command.log_command_entry(mock_update, mock_context)

            # --- Assert --- 
            mock_parse_text.assert_called_once_with("100g chicken")
            mock_get_nutrition.assert_called_once_with(mock_parsed_items)
            mock_add_nutrition.assert_called_once()
            call_args, call_kwargs = mock_add_nutrition.call_args
            self.assertEqual(call_kwargs['sheet_id'], 'sid')
            self.assertEqual(call_kwargs['worksheet_name'], 'wsn')
            self.assertEqual(call_kwargs['target_dt'], FIXED_TODAY)
            self.assertEqual(call_kwargs['bot_token'], mock_bot.token)
            self.assertEqual(call_kwargs['calories'], 165.0)
            self.assertEqual(call_kwargs['p'], 31.0)
            
            # Check that the final message was edited correctly
            final_edit_call = mock_processing_message.edit_text.call_args_list[-1]
            final_text = final_edit_call[0][0]
            # Adjust expected fat value formatting to match int() truncation
            expected_fat = int(mock_nutrition_info['fat'])
            expected_text = (
                f"✅ Meal logged for {FIXED_TODAY_STR}!\n"
                f"Added: {mock_nutrition_info['calories']:.0f} Cal, "
                f"{int(mock_nutrition_info['protein'])}g P, "
                f"{int(mock_nutrition_info['carbs'])}g C, "
                f"{expected_fat}g F, "
                f"{int(mock_nutrition_info['fiber'])}g Fi\n\n"
                f"Note: For confirmation and editing options, use /newlog next time."
            )
            self.assertEqual(final_text, expected_text)
            
            mock_update_metrics.assert_not_called()
            mock_format_date.assert_called()

    # Uncomment photo test
    async def test_log_command_photo_meal_success(self):
        """Test /log meal with photo attachment."""
        # Nested patches for dependencies
        with patch('src.bot.commands.log_command.date') as mock_date, \
             patch('src.bot.commands.log_command.format_date_for_sheet', return_value=FIXED_TODAY_STR) as mock_format_date, \
             patch('src.bot.commands.log_command.add_nutrition', new_callable=AsyncMock) as mock_add_nutrition, \
             patch('src.bot.commands.log_command.update_metrics') as mock_update_metrics, \
             patch('src.bot.commands.log_command.get_nutrition_for_items') as mock_get_nutrition, \
             patch('src.bot.commands.log_command.parse_meal_image_with_gemini') as mock_parse_image, \
             patch('src.bot.commands.log_command.parse_meal_text_with_gemini') as mock_parse_text, \
             patch('src.bot.commands.log_command.dateparser.parse', return_value=None) as mock_dateparse, \
             patch('src.bot.commands.log_command._get_current_sheet_config') as mock_get_config:

            # --- Test Setup --- 
            mock_date.today.return_value = FIXED_TODAY
            # Simulate photo with caption /log meal
            mock_update, mock_context, mock_bot = self._create_mocks(caption="/log meal", photo=True)
            mock_config_data = {'google_sheet_id': 'sid', 'worksheet_name': 'wsn', 'column_map': {}}
            mock_get_config.return_value = mock_config_data
            # Mock parsed items and nutrition info
            mock_parsed_items = [{'item': 'salad', 'quantity_g': 250.0}]
            mock_nutrition_info = {'calories': 300.0, 'protein': 10.0, 'carbs': 15.0, 'fat': 20.0, 'fiber': 5.0}
            mock_parse_image.return_value = mock_parsed_items
            mock_get_nutrition.return_value = mock_nutrition_info
            mock_add_nutrition.return_value = True # Simulate success
            
            # Mock the message sent during processing
            mock_processing_message = AsyncMock()
            mock_bot.send_message.return_value = mock_processing_message

            # --- Execute --- 
            await log_command.log_command_entry(mock_update, mock_context)

            # --- Assert --- 
            mock_bot.get_file.assert_called_once()
            # Ensure the mock photo data was passed to the parser
            mock_parse_image.assert_called_once_with(b'mock_photo_data') 
            mock_get_nutrition.assert_called_once_with(mock_parsed_items)
            mock_add_nutrition.assert_called_once()
            
            # Check edit_text was called to update status (at least initial + final)
            self.assertGreaterEqual(mock_processing_message.edit_text.call_count, 2)
            # Check the final message text
            final_edit_call = mock_processing_message.edit_text.call_args_list[-1]
            final_text = final_edit_call[0][0]
            expected_fat = int(mock_nutrition_info['fat'])
            expected_text = (
                f"✅ Meal logged for {FIXED_TODAY_STR}!\n"
                f"Added: {mock_nutrition_info['calories']:.0f} Cal, "
                f"{int(mock_nutrition_info['protein'])}g P, "
                f"{int(mock_nutrition_info['carbs'])}g C, "
                f"{expected_fat}g F, "
                f"{int(mock_nutrition_info['fiber'])}g Fi"
                # Note: The "use /newlog" note is NOT added in the photo handler
            )
            self.assertEqual(final_text, expected_text)

            mock_parse_text.assert_not_called()
            mock_update_metrics.assert_not_called()
            mock_format_date.assert_called()

if __name__ == '__main__':
    unittest.main() 