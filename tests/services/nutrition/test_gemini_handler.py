import unittest
import json
from unittest.mock import patch, MagicMock, ANY

# Module to test
from src.services.nutrition import gemini_handler

# Mock AIModelManager and its methods upfront
@patch('src.services.nutrition.gemini_handler.AIModelManager')
class TestGeminiHandler(unittest.TestCase):

    # --- Tests for _estimate_nutrition_with_gemini --- #

    def test_estimate_nutrition_success(self, MockAIModelManager):
        """Test successful nutrition estimation."""
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        # Test with markdown code fence
        mock_response.text = '```json\n{"calories": 250.0, "protein": 10.5, "carbs": 30.0, "fat": 8.2, "fiber": 3.1}\n```'
        mock_model_instance.generate_content.return_value = mock_response
        MockAIModelManager.get_model.return_value = mock_model_instance

        item_name = "chicken breast"
        quantity_g = 150.0
        expected_result = {
            'calories': 250.0,
            'protein': 10.5,
            'carbs': 30.0,
            'fat': 8.2,
            'fiber': 3.1,
            'source': 'Gemini (Estimate)'
        }

        # Clear cache before test if needed
        gemini_handler._estimate_nutrition_with_gemini.cache_clear()

        result = gemini_handler._estimate_nutrition_with_gemini(item_name, quantity_g)
        self.assertEqual(result, expected_result)
        MockAIModelManager.get_model.assert_called_once_with('nutrition')
        mock_model_instance.generate_content.assert_called_once_with(
            ANY, # Don't need to check the exact prompt string
            request_options={'timeout': 30}
        )

    def test_estimate_nutrition_invalid_json(self, MockAIModelManager):
        """Test handling of invalid JSON response."""
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"calories": 100, protein: 5' # Missing quotes
        mock_model_instance.generate_content.return_value = mock_response
        MockAIModelManager.get_model.return_value = mock_model_instance

        gemini_handler._estimate_nutrition_with_gemini.cache_clear()
        result = gemini_handler._estimate_nutrition_with_gemini("test", 100)
        self.assertIsNone(result)

    def test_estimate_nutrition_missing_keys(self, MockAIModelManager):
        """Test handling of JSON missing required keys."""
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"calories": 100, "protein": 5}' # Missing other keys
        mock_model_instance.generate_content.return_value = mock_response
        MockAIModelManager.get_model.return_value = mock_model_instance

        gemini_handler._estimate_nutrition_with_gemini.cache_clear()
        result = gemini_handler._estimate_nutrition_with_gemini("test", 100)
        self.assertIsNone(result)

    def test_estimate_nutrition_non_numeric_values(self, MockAIModelManager):
        """Test handling of JSON with non-numeric values."""
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"calories": "high", "protein": 10.5, "carbs": 30.0, "fat": 8.2, "fiber": 3.1}'
        mock_model_instance.generate_content.return_value = mock_response
        MockAIModelManager.get_model.return_value = mock_model_instance

        gemini_handler._estimate_nutrition_with_gemini.cache_clear()
        result = gemini_handler._estimate_nutrition_with_gemini("test", 100)
        self.assertIsNone(result)

    def test_estimate_nutrition_not_a_dict(self, MockAIModelManager):
        """Test handling when response is not a JSON object."""
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[1, 2, 3]' # JSON array, not object
        mock_model_instance.generate_content.return_value = mock_response
        MockAIModelManager.get_model.return_value = mock_model_instance

        gemini_handler._estimate_nutrition_with_gemini.cache_clear()
        result = gemini_handler._estimate_nutrition_with_gemini("test", 100)
        self.assertIsNone(result)

    def test_estimate_nutrition_api_error(self, MockAIModelManager):
        """Test handling of Gemini API call failure."""
        mock_model_instance = MagicMock()
        mock_model_instance.generate_content.side_effect = Exception("Service Unavailable")
        MockAIModelManager.get_model.return_value = mock_model_instance

        gemini_handler._estimate_nutrition_with_gemini.cache_clear()
        result = gemini_handler._estimate_nutrition_with_gemini("test", 100)
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main() 