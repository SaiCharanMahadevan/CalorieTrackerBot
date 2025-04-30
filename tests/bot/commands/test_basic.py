import unittest
from unittest.mock import patch, AsyncMock, MagicMock # Import MagicMock
import html

# Module to test
from src.bot.commands import basic

# No class-level patch
class TestBasicCommands(unittest.IsolatedAsyncioTestCase):

    # Helper to create mock Update and Context
    def _create_mocks(self):
        mock_update = AsyncMock()
        mock_context = AsyncMock()
        mock_message = AsyncMock()
        mock_user = MagicMock() # Use MagicMock for user
        mock_chat = AsyncMock()
        mock_bot = AsyncMock()

        # Set return value for mention_html on MagicMock
        mock_user.mention_html.return_value = "<testuser>" 
        mock_update.effective_user = mock_user
        mock_update.message = mock_message
        mock_message.chat = mock_chat
        # Ensure effective_chat.id is set for help_command check
        mock_update.effective_chat = mock_chat 
        mock_chat.id = 12345
        # mock_message.chat_id = 12345 # Keep for consistency if needed elsewhere
        
        mock_update._bot = mock_bot 
        mock_bot.token = "dummytoken:1234"

        return mock_update, mock_context, mock_bot

    # Remove patch and mock_config argument
    async def test_start_command(self):
        """Test the /start command replies correctly."""
        mock_update, mock_context, _ = self._create_mocks()

        await basic.start(mock_update, mock_context)

        mock_update.message.reply_html.assert_called_once()
        call_args = mock_update.message.reply_html.call_args[0]
        # Assertion should now work as mention_html is a string
        self.assertIn("Hi <testuser>!", call_args[0]) 
        self.assertIn("/log command", call_args[0])
        self.assertIn("/help", call_args[0])

    # Remove patch and mock_config argument
    async def test_help_command(self):
        """Test the /help command sends the correct message via bot."""
        mock_update, mock_context, mock_bot = self._create_mocks()
        
        await basic.help_command(mock_update, mock_context)
        
        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args[1]
        
        # Check against update.effective_chat.id which is set to 12345
        self.assertEqual(call_kwargs.get('chat_id'), 12345) 
        self.assertIn("<b>Commands:</b>", call_kwargs.get('text'))
        self.assertIn("/log", call_kwargs.get('text'))
        self.assertIn("/newlog", call_kwargs.get('text'))
        self.assertIn("weight", call_kwargs.get('text')) # Check if metric from mock_config is included
        self.assertIn("sleep", call_kwargs.get('text'))
        self.assertEqual(call_kwargs.get('parse_mode'), 'HTML')
        
    # Unknown command doesn't rely on the map, so no patch needed?
    # Let's verify basic.py - Yes, unknown_command doesn't use the map.
    async def test_unknown_command(self):
        """Test the unknown command handler replies correctly."""
        mock_update, mock_context, _ = self._create_mocks()

        await basic.unknown_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once_with(
            "Sorry, I didn't understand that command. Type /help to see available commands."
        )

if __name__ == '__main__':
    unittest.main() 