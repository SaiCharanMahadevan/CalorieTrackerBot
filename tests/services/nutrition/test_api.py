import unittest
from unittest.mock import patch, MagicMock, call
from typing import List, Dict, Any

# Module to test
from src.services.nutrition import api

class TestNutritionApi(unittest.TestCase):

    def _create_mock_item(self, name: str, quantity: float) -> Dict[str, Any]:
        return {"item": name, "quantity_g": quantity}

    @patch('src.services.nutrition.api._estimate_nutrition_with_gemini')
    @patch('src.services.nutrition.api._get_usda_nutrition_details')
    @patch('src.services.nutrition.api._choose_best_usda_match')
    @patch('src.services.nutrition.api._search_usda_food')
    def test_get_nutrition_success_usda_path(
        self, mock_search_usda, mock_choose_match, mock_get_details, mock_estimate_gemini
    ):
        """Test successful path using USDA data."""
        items = [self._create_mock_item("apple", 100), self._create_mock_item("banana", 150)]

        # Mock USDA search results
        mock_search_usda.side_effect = [
            [{'fdcId': 1, 'description': 'Apple, raw'}],  # For apple
            [{'fdcId': 2, 'description': 'Banana, raw'}] # For banana
        ]

        # Mock choice of best match
        mock_choose_match.side_effect = [1, 2] # Choose the first FDC ID for both

        # Mock USDA nutrition details
        mock_get_details.side_effect = [
            {'calories': 52.0, 'protein': 0.3, 'carbs': 14.0, 'fat': 0.2, 'fiber': 2.4, 'source': 'USDA (FDC ID: 1)'}, # Apple 100g
            {'calories': 134.0, 'protein': 1.6, 'carbs': 34.0, 'fat': 0.5, 'fiber': 3.9, 'source': 'USDA (FDC ID: 2)'} # Banana 150g (calculated)
        ]

        expected_result = {
            'calories': round(52.0 + 134.0),
            'protein': round(0.3 + 1.6),
            'carbs': round(14.0 + 34.0),
            'fat': round(0.2 + 0.5),
            'fiber': round(2.4 + 3.9)
        }

        result = api.get_nutrition_for_items(items)

        self.assertEqual(result, expected_result)
        mock_search_usda.assert_has_calls([call("apple"), call("banana")])
        mock_choose_match.assert_has_calls([
            call("apple", [{'fdcId': 1, 'description': 'Apple, raw'}]),
            call("banana", [{'fdcId': 2, 'description': 'Banana, raw'}])
        ])
        mock_get_details.assert_has_calls([call(1, 100), call(2, 150)])
        mock_estimate_gemini.assert_not_called() # Gemini fallback should not be called

    @patch('src.services.nutrition.api._estimate_nutrition_with_gemini')
    @patch('src.services.nutrition.api._get_usda_nutrition_details')
    @patch('src.services.nutrition.api._choose_best_usda_match')
    @patch('src.services.nutrition.api._search_usda_food')
    def test_get_nutrition_fallback_to_gemini(
        self, mock_search_usda, mock_choose_match, mock_get_details, mock_estimate_gemini
    ):
        """Test path where USDA search fails and Gemini is used."""
        items = [self._create_mock_item("unknown food", 200)]

        # Mock USDA search returns nothing
        mock_search_usda.return_value = None

        # Mock Gemini estimation
        mock_estimate_gemini.return_value = {
            'calories': 300.0, 'protein': 10.0, 'carbs': 40.0, 'fat': 12.0, 'fiber': 5.0, 'source': 'Gemini (Estimate)'
        }

        expected_result = {
            'calories': 300, 'protein': 10, 'carbs': 40, 'fat': 12, 'fiber': 5
        }

        result = api.get_nutrition_for_items(items)

        self.assertEqual(result, expected_result)
        mock_search_usda.assert_called_once_with("unknown food")
        mock_choose_match.assert_not_called()
        mock_get_details.assert_not_called()
        mock_estimate_gemini.assert_called_once_with("unknown food", 200)

    @patch('src.services.nutrition.api._estimate_nutrition_with_gemini')
    @patch('src.services.nutrition.api._get_usda_nutrition_details')
    @patch('src.services.nutrition.api._choose_best_usda_match')
    @patch('src.services.nutrition.api._search_usda_food')
    def test_get_nutrition_usda_details_fail_fallback_gemini(
        self, mock_search_usda, mock_choose_match, mock_get_details, mock_estimate_gemini
    ):
        """Test path where USDA details fetch fails and Gemini is used."""
        items = [self._create_mock_item("orange", 120)]

        # Mock USDA search success
        mock_search_usda.return_value = [{'fdcId': 123, 'description': 'Orange, raw'}]

        # Mock choice success
        mock_choose_match.return_value = 123

        # Mock USDA details fetch failure
        mock_get_details.return_value = None

        # Mock Gemini estimation
        mock_estimate_gemini.return_value = {
            'calories': 60.0, 'protein': 1.0, 'carbs': 15.0, 'fat': 0.1, 'fiber': 3.0, 'source': 'Gemini (Estimate)'
        }

        expected_result = {
            'calories': 60, 'protein': 1, 'carbs': 15, 'fat': 0, 'fiber': 3
        }

        result = api.get_nutrition_for_items(items)

        self.assertEqual(result, expected_result)
        mock_search_usda.assert_called_once_with("orange")
        mock_choose_match.assert_called_once_with("orange", [{'fdcId': 123, 'description': 'Orange, raw'}])
        mock_get_details.assert_called_once_with(123, 120)
        mock_estimate_gemini.assert_called_once_with("orange", 120)

    def test_get_nutrition_empty_list(self):
        """Test with an empty input list."""
        result = api.get_nutrition_for_items([])
        self.assertIsNone(result)

    @patch('src.services.nutrition.api.logger') # Patch logger to check warnings
    def test_get_nutrition_invalid_items(self, mock_logger):
        """Test with items having missing name or zero/negative quantity."""
        items = [
            self._create_mock_item("apple", 100), # Valid
            {"item": None, "quantity_g": 50}, # Invalid (no name)
            self._create_mock_item("banana", 0), # Invalid (zero quantity)
            self._create_mock_item("orange", -10) # Invalid (negative quantity)
        ]

        # Mock successful processing for the valid item (doesn't matter which path)
        with patch('src.services.nutrition.api._search_usda_food', return_value=[{'fdcId': 1, 'description': 'Apple, raw'}]), \
             patch('src.services.nutrition.api._choose_best_usda_match', return_value=1), \
             patch('src.services.nutrition.api._get_usda_nutrition_details', return_value={'calories': 52.0, 'protein': 0.3, 'carbs': 14.0, 'fat': 0.2, 'fiber': 2.4, 'source': 'USDA'}), \
             patch('src.services.nutrition.api._estimate_nutrition_with_gemini') as mock_gemini:

            expected_result = {'calories': 52, 'protein': 0, 'carbs': 14, 'fat': 0, 'fiber': 2}
            result = api.get_nutrition_for_items(items)

            self.assertEqual(result, expected_result)
            mock_gemini.assert_not_called() # Should not be called for invalid items

            # Check that warnings were logged for invalid items
            self.assertTrue(any("Skipping invalid item" in call_args[0][0] for call_args in mock_logger.warning.call_args_list))


    @patch('src.services.nutrition.api._estimate_nutrition_with_gemini')
    @patch('src.services.nutrition.api._get_usda_nutrition_details')
    @patch('src.services.nutrition.api._choose_best_usda_match')
    @patch('src.services.nutrition.api._search_usda_food')
    def test_get_nutrition_all_failed(
        self, mock_search_usda, mock_choose_match, mock_get_details, mock_estimate_gemini
    ):
        """Test scenario where all items fail processing."""
        items = [self._create_mock_item("weird item 1", 50), self._create_mock_item("weird item 2", 60)]

        # Mock all steps to return failure/None
        mock_search_usda.return_value = None
        mock_estimate_gemini.return_value = None # Gemini also fails

        result = api.get_nutrition_for_items(items)

        self.assertIsNone(result) # Expect None if no items were processed successfully
        mock_search_usda.assert_has_calls([call("weird item 1"), call("weird item 2")])
        mock_choose_match.assert_not_called()
        mock_get_details.assert_not_called()
        mock_estimate_gemini.assert_has_calls([call("weird item 1", 50), call("weird item 2", 60)])

    @patch('src.services.nutrition.api._estimate_nutrition_with_gemini')
    @patch('src.services.nutrition.api._get_usda_nutrition_details')
    @patch('src.services.nutrition.api._choose_best_usda_match')
    @patch('src.services.nutrition.api._search_usda_food')
    def test_get_nutrition_mixed_success_failure(
        self, mock_search_usda, mock_choose_match, mock_get_details, mock_estimate_gemini
    ):
        """Test with a mix of items that succeed and fail."""
        items = [
            self._create_mock_item("apple", 100), # Success via USDA
            self._create_mock_item("weird food", 75) # Fails all lookups
        ]

        # Mock USDA path for apple
        mock_search_usda.side_effect = [[{'fdcId': 1, 'description': 'Apple, raw'}], None]
        mock_choose_match.side_effect = [1]
        mock_get_details.side_effect = [{'calories': 52.0, 'protein': 0.3, 'carbs': 14.0, 'fat': 0.2, 'fiber': 2.4, 'source': 'USDA'}]

        # Mock Gemini failure for weird food
        mock_estimate_gemini.side_effect = [None] # Only called for the second item

        expected_result = {'calories': 52, 'protein': 0, 'carbs': 14, 'fat': 0, 'fiber': 2} # Only apple's data

        result = api.get_nutrition_for_items(items)

        self.assertEqual(result, expected_result)
        mock_search_usda.assert_has_calls([call("apple"), call("weird food")])
        mock_choose_match.assert_called_once_with("apple", [{'fdcId': 1, 'description': 'Apple, raw'}])
        mock_get_details.assert_called_once_with(1, 100)
        mock_estimate_gemini.assert_called_once_with("weird food", 75)

if __name__ == '__main__':
    unittest.main() 