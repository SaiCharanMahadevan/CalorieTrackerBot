import unittest
import json
import requests
from unittest.mock import patch, MagicMock

# Module to test
from src.services.nutrition import usda_handler

# Mock config directly where used in the handler
@patch('src.services.nutrition.usda_handler.config') 
class TestUsdaHandler(unittest.TestCase):

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_search_usda_food_success(self, mock_get_key, mock_requests_get, mock_config):
        """Test successful USDA food search."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_get_key.return_value = "VALID_KEY"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'foods': [
                {'fdcId': 1, 'description': 'Apple, raw, with skin'},
                {'fdcId': 2, 'description': 'Applesauce, unsweetened'},
                {'fdcId': 3, 'description': 'Apple juice, canned or bottled'}
            ]
        }
        mock_requests_get.return_value = mock_response

        usda_handler._search_usda_food.cache_clear() # Clear cache
        result = usda_handler._search_usda_food("apple")

        expected_candidates = [
            {'fdcId': 1, 'description': 'Apple, raw, with skin'},
            {'fdcId': 2, 'description': 'Applesauce, unsweetened'},
            {'fdcId': 3, 'description': 'Apple juice, canned or bottled'}
        ]
        self.assertEqual(result, expected_candidates)
        mock_get_key.assert_called_once_with("USDA_API_KEY", mock_config.USDA_API_KEY)
        mock_requests_get.assert_called_once_with(
            f"{mock_config.USDA_API_BASE_URL}/foods/search",
            params={
                'api_key': "VALID_KEY",
                'query': "apple",
                'pageSize': 5,
                'dataType': 'Foundation,SR Legacy,Survey (FNDDS)'
            },
            timeout=10
        )

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_search_usda_food_no_results(self, mock_get_key, mock_requests_get, mock_config):
        """Test search returning no results."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_get_key.return_value = "VALID_KEY"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'foods': []}
        mock_requests_get.return_value = mock_response

        usda_handler._search_usda_food.cache_clear()
        result = usda_handler._search_usda_food("nonexistent food")
        self.assertIsNone(result)

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_search_usda_food_api_error(self, mock_get_key, mock_requests_get, mock_config):
        """Test handling of requests library errors."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_get_key.return_value = "VALID_KEY"
        mock_requests_get.side_effect = requests.exceptions.RequestException("Connection error")

        usda_handler._search_usda_food.cache_clear()
        result = usda_handler._search_usda_food("apple")
        self.assertIsNone(result)
        
    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_search_usda_food_http_error(self, mock_get_key, mock_requests_get, mock_config):
        """Test handling of HTTP errors (e.g., 401 Unauthorized)."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_get_key.return_value = "INVALID_KEY"
        
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Unauthorized")
        mock_requests_get.return_value = mock_response

        usda_handler._search_usda_food.cache_clear()
        result = usda_handler._search_usda_food("apple")
        self.assertIsNone(result)
        mock_response.raise_for_status.assert_called_once()

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_search_usda_food_json_error(self, mock_get_key, mock_requests_get, mock_config):
        """Test handling of JSON decoding errors."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_get_key.return_value = "VALID_KEY"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_requests_get.return_value = mock_response

        usda_handler._search_usda_food.cache_clear()
        result = usda_handler._search_usda_food("apple")
        self.assertIsNone(result)
        
    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_search_usda_no_api_key(self, mock_get_key, mock_requests_get, mock_config):
        """Test that search is skipped if API key is missing."""
        mock_get_key.return_value = None # Simulate missing key

        usda_handler._search_usda_food.cache_clear()
        result = usda_handler._search_usda_food("apple")

        self.assertIsNone(result)
        mock_requests_get.assert_not_called() # Request should not be made

    # --- Tests for _get_usda_nutrition_details --- #

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_get_details_success_label_nutrients(self, mock_get_key, mock_requests_get, mock_config):
        """Test successful detail fetch using labelNutrients."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        # Mock nutrient IDs needed for fiber lookup
        mock_config.NUTRIENT_ID_MAP = {'fiber': 1079}
        mock_get_key.return_value = "VALID_KEY"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'fdcId': 12345,
            'description': 'Test Food',
            'labelNutrients': {
                'calories': {'value': 200.0},
                'protein': {'value': 10.0},
                'carbohydrates': {'value': 30.0},
                'fat': {'value': 5.0}
            },
            'foodNutrients': [
                # Fiber is often only in foodNutrients
                {'nutrient': {'id': 1079, 'name': 'Fiber, total dietary'}, 'amount': 3.0} 
            ]
        }
        mock_requests_get.return_value = mock_response

        fdc_id = 12345
        quantity_g = 150.0

        usda_handler._get_usda_nutrition_details.cache_clear()
        result = usda_handler._get_usda_nutrition_details(fdc_id, quantity_g)

        expected_nutrition = {
            'calories': (200.0 / 100.0) * quantity_g,
            'protein': (10.0 / 100.0) * quantity_g,
            'carbs': (30.0 / 100.0) * quantity_g,
            'fat': (5.0 / 100.0) * quantity_g,
            'fiber': (3.0 / 100.0) * quantity_g,
            'source': f'USDA (FDC ID: {fdc_id})'
        }
        self.assertIsNotNone(result)
        for key, value in expected_nutrition.items():
            self.assertIn(key, result)
            self.assertAlmostEqual(result[key], value, places=5)

        mock_get_key.assert_called_once_with("USDA_API_KEY", mock_config.USDA_API_KEY)
        mock_requests_get.assert_called_once_with(
            f"{mock_config.USDA_API_BASE_URL}/food/{fdc_id}",
            params={'api_key': "VALID_KEY"},
            timeout=10
        )

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_get_details_success_food_nutrients_fallback(self, mock_get_key, mock_requests_get, mock_config):
        """Test successful detail fetch using foodNutrients fallback."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_config.NUTRIENT_ID_MAP = {
            'calories': 208, 'protein': 203, 'carbs': 205,
            'fat': 204, 'fiber': 291
        }
        mock_get_key.return_value = "VALID_KEY"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'fdcId': 54321,
            'description': 'Fallback Food',
            'labelNutrients': None, # Simulate missing labelNutrients
            'foodNutrients': [
                {'nutrient': {'id': 208}, 'amount': 150.0}, # Calories
                {'nutrient': {'id': 203}, 'amount': 8.0},  # Protein
                {'nutrient': {'id': 205}, 'amount': 25.0}, # Carbs
                {'nutrient': {'id': 204}, 'amount': 4.0},  # Fat
                {'nutrient': {'id': 291}, 'amount': 2.0}   # Fiber
            ]
        }
        mock_requests_get.return_value = mock_response

        fdc_id = 54321
        quantity_g = 50.0

        usda_handler._get_usda_nutrition_details.cache_clear()
        result = usda_handler._get_usda_nutrition_details(fdc_id, quantity_g)

        expected_nutrition = {
            'calories': (150.0 / 100.0) * quantity_g,
            'protein': (8.0 / 100.0) * quantity_g,
            'carbs': (25.0 / 100.0) * quantity_g,
            'fat': (4.0 / 100.0) * quantity_g,
            'fiber': (2.0 / 100.0) * quantity_g,
            'source': f'USDA (FDC ID: {fdc_id})'
        }
        self.assertIsNotNone(result)
        for key, value in expected_nutrition.items():
             self.assertIn(key, result)
             self.assertAlmostEqual(result[key], value, places=5)

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_get_details_missing_nutrients(self, mock_get_key, mock_requests_get, mock_config):
        """Test fetch where some nutrients are missing in the response."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_config.NUTRIENT_ID_MAP = {'fiber': 1079}
        mock_get_key.return_value = "VALID_KEY"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'fdcId': 11111,
            'labelNutrients': {
                'calories': {'value': 100.0}, # Missing protein, carbs, fat
            },
            'foodNutrients': [] # Missing fiber too
        }
        mock_requests_get.return_value = mock_response

        fdc_id = 11111
        quantity_g = 200.0

        usda_handler._get_usda_nutrition_details.cache_clear()
        result = usda_handler._get_usda_nutrition_details(fdc_id, quantity_g)

        expected_nutrition = {
            'calories': (100.0 / 100.0) * quantity_g,
            'protein': 0.0, # Should default to 0
            'carbs': 0.0,
            'fat': 0.0,
            'fiber': 0.0,
            'source': f'USDA (FDC ID: {fdc_id})'
        }
        self.assertIsNotNone(result)
        for key, value in expected_nutrition.items():
             self.assertIn(key, result)
             self.assertAlmostEqual(result[key], value, places=5)

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_get_details_non_numeric_value(self, mock_get_key, mock_requests_get, mock_config):
        """Test handling of non-numeric nutrient values in response."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_config.NUTRIENT_ID_MAP = {'fiber': 1079}
        mock_get_key.return_value = "VALID_KEY"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'fdcId': 22222,
            'labelNutrients': {
                'calories': {'value': 'N/A'}, # Non-numeric
                'protein': {'value': 10.0},
                'carbohydrates': {'value': 30.0},
                'fat': {'value': 5.0}
            },
            'foodNutrients': []
        }
        mock_requests_get.return_value = mock_response

        fdc_id = 22222
        quantity_g = 100.0

        usda_handler._get_usda_nutrition_details.cache_clear()
        result = usda_handler._get_usda_nutrition_details(fdc_id, quantity_g)

        # Expect calories to default to 0 due to conversion error
        expected_nutrition = {
            'calories': 0.0, 
            'protein': (10.0 / 100.0) * quantity_g,
            'carbs': (30.0 / 100.0) * quantity_g,
            'fat': (5.0 / 100.0) * quantity_g,
            'fiber': 0.0,
            'source': f'USDA (FDC ID: {fdc_id})'
        }
        self.assertIsNotNone(result)
        for key, value in expected_nutrition.items():
             self.assertIn(key, result)
             self.assertAlmostEqual(result[key], value, places=5)

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_get_details_api_error(self, mock_get_key, mock_requests_get, mock_config):
        """Test handling of requests library errors during detail fetch."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_get_key.return_value = "VALID_KEY"
        mock_requests_get.side_effect = requests.exceptions.Timeout("Timeout")

        usda_handler._get_usda_nutrition_details.cache_clear()
        result = usda_handler._get_usda_nutrition_details(123, 100)
        self.assertIsNone(result)

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_get_details_http_error(self, mock_get_key, mock_requests_get, mock_config):
        """Test handling of HTTP errors during detail fetch."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_get_key.return_value = "VALID_KEY"
        
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Not Found")
        mock_requests_get.return_value = mock_response

        usda_handler._get_usda_nutrition_details.cache_clear()
        result = usda_handler._get_usda_nutrition_details(999, 100)
        self.assertIsNone(result)
        mock_response.raise_for_status.assert_called_once()
        
    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_get_details_json_error(self, mock_get_key, mock_requests_get, mock_config):
        """Test handling of JSON decoding errors during detail fetch."""
        mock_config.USDA_API_BASE_URL = "http://mock-usda.com"
        mock_get_key.return_value = "VALID_KEY"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Bad JSON", "", 0)
        mock_requests_get.return_value = mock_response

        usda_handler._get_usda_nutrition_details.cache_clear()
        result = usda_handler._get_usda_nutrition_details(123, 100)
        self.assertIsNone(result)

    @patch('src.services.nutrition.usda_handler.requests.get')
    @patch('src.services.nutrition.usda_handler._get_api_key')
    def test_get_details_no_api_key(self, mock_get_key, mock_requests_get, mock_config):
        """Test that detail fetch is skipped if API key is missing."""
        mock_get_key.return_value = None # Simulate missing key

        usda_handler._get_usda_nutrition_details.cache_clear()
        result = usda_handler._get_usda_nutrition_details(123, 100)

        self.assertIsNone(result)
        mock_requests_get.assert_not_called() # Request should not be made

if __name__ == '__main__':
    unittest.main() 