import unittest
from unittest.mock import patch, MagicMock, call
from typing import List, Dict, Any

# Module to test
from src.services.nutrition import api

class TestNutritionApi(unittest.TestCase):

    def _create_mock_item(self, name: str, quantity: float) -> Dict[str, Any]:
        return {"item": name, "quantity_g": quantity}

    @patch('src.services.nutrition.api._estimate_nutrition_with_gemini')
    def test_get_nutrition_success_gemini_path(self, mock_estimate_gemini):
        """Test successful path using ONLY Gemini data."""
        items = [self._create_mock_item("apple", 100), self._create_mock_item("banana", 150)]

        # Mock Gemini estimations
        mock_estimate_gemini.side_effect = [
            {'calories': 55.0, 'protein': 0.5, 'carbs': 15.0, 'fat': 0.3, 'fiber': 2.5, 'source': 'Gemini (Estimate)'}, # Apple 100g
            {'calories': 140.0, 'protein': 1.5, 'carbs': 35.0, 'fat': 0.6, 'fiber': 4.0, 'source': 'Gemini (Estimate)'} # Banana 150g
        ]

        expected_result = {
            'calories': round(55.0 + 140.0),
            'protein': round(0.5 + 1.5),
            'carbs': round(15.0 + 35.0),
            'fat': round(0.3 + 0.6),
            'fiber': round(2.5 + 4.0)
        }

        result = api.get_nutrition_for_items(items)

        self.assertEqual(result, expected_result)
        # Verify Gemini was called directly for each item
        mock_estimate_gemini.assert_has_calls([call("apple", 100), call("banana", 150)])

    # Test renamed and simplified: only tests Gemini direct call
    @patch('src.services.nutrition.api._estimate_nutrition_with_gemini')
    def test_get_nutrition_single_item_gemini(self, mock_estimate_gemini):
        """Test successful Gemini estimation for a single item."""
        items = [self._create_mock_item("unknown food", 200)]

        # Mock Gemini estimation
        mock_estimate_gemini.return_value = {
            'calories': 300.0, 'protein': 10.0, 'carbs': 40.0, 'fat': 12.0, 'fiber': 5.0, 'source': 'Gemini (Estimate)'
        }

        expected_result = {
            'calories': 300, 'protein': 10, 'carbs': 40, 'fat': 12, 'fiber': 5
        }

        result = api.get_nutrition_for_items(items)

        self.assertEqual(result, expected_result)
        # Verify Gemini was called
        mock_estimate_gemini.assert_called_once_with("unknown food", 200)

    def test_get_nutrition_empty_list(self):
        """Test with an empty input list."""
        result = api.get_nutrition_for_items([])
        self.assertIsNone(result)

    @patch('src.services.nutrition.api.logger') # Patch logger to check warnings
    @patch('src.services.nutrition.api._estimate_nutrition_with_gemini') # Still need to patch Gemini
    def test_get_nutrition_invalid_items(self, mock_estimate_gemini, mock_logger):
        """Test with items having missing name or zero/negative quantity."""
        items = [
            self._create_mock_item("apple", 100), # Valid
            {"item": None, "quantity_g": 50}, # Invalid (no name)
            self._create_mock_item("banana", 0), # Invalid (zero quantity)
            self._create_mock_item("orange", -10) # Invalid (negative quantity)
        ]

        # Mock successful processing for the valid item using Gemini
        mock_estimate_gemini.return_value = {'calories': 52.0, 'protein': 0.3, 'carbs': 14.0, 'fat': 0.2, 'fiber': 2.4, 'source': 'Gemini'}

        expected_result = {'calories': 52, 'protein': 0, 'carbs': 14, 'fat': 0, 'fiber': 2} # Only apple's data
        result = api.get_nutrition_for_items(items)

        self.assertEqual(result, expected_result)
        # Gemini should only be called for the valid item
        mock_estimate_gemini.assert_called_once_with("apple", 100)

        # Check that warnings were logged for invalid items
        self.assertTrue(any("Skipping invalid item" in call_args[0][0] for call_args in mock_logger.warning.call_args_list))

    # Test simplified to only check Gemini failure
    @patch('src.services.nutrition.api._estimate_nutrition_with_gemini')
    def test_get_nutrition_all_failed_gemini(self, mock_estimate_gemini):
        """Test scenario where Gemini estimation fails for all items."""
        items = [self._create_mock_item("weird item 1", 50), self._create_mock_item("weird item 2", 60)]

        # Mock Gemini to fail
        mock_estimate_gemini.return_value = None

        result = api.get_nutrition_for_items(items)

        self.assertIsNone(result) # Expect None if no items were processed successfully
        # Verify Gemini was called for both items
        mock_estimate_gemini.assert_has_calls([call("weird item 1", 50), call("weird item 2", 60)])

    # Test simplified: one success (Gemini), one failure (Gemini)
    @patch('src.services.nutrition.api._estimate_nutrition_with_gemini')
    def test_get_nutrition_mixed_success_failure_gemini(self, mock_estimate_gemini):
        """Test with a mix of items where Gemini succeeds and fails."""
        items = [
            self._create_mock_item("apple", 100),       # Success via Gemini
            self._create_mock_item("weird food", 75)   # Fails Gemini lookup
        ]

        # Mock Gemini results: success for apple, failure for weird food
        mock_estimate_gemini.side_effect = [
            {'calories': 52.0, 'protein': 0.3, 'carbs': 14.0, 'fat': 0.2, 'fiber': 2.4, 'source': 'Gemini'},
            None
        ]

        expected_result = {'calories': 52, 'protein': 0, 'carbs': 14, 'fat': 0, 'fiber': 2} # Only apple's data

        result = api.get_nutrition_for_items(items)

        self.assertEqual(result, expected_result)
        # Verify Gemini was called for both
        mock_estimate_gemini.assert_has_calls([call("apple", 100), call("weird food", 75)])

if __name__ == '__main__':
    unittest.main() 