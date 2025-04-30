"""Handles fetching nutritional information from the USDA FoodData Central API."""

import requests
import logging
import os
import json
from functools import lru_cache # Import lru_cache
from typing import List, Dict, Any # Keep typing for consistency

# Project Imports - Need config for API keys/URLs/IDs
from src.config import config 

logger = logging.getLogger(__name__)

# --- Private Helper Functions ---

def _get_api_key(key_name, config_value):
    """Get API key from environment variables or config."""
    return os.environ.get(key_name, config_value)

@lru_cache(maxsize=32) # Smaller cache for search results?
def _search_usda_food(item_name: str) -> list[dict] | None:
    """Searches the USDA database for a food item and returns top candidate details.

    Args:
        item_name: The name of the food item to search for.

    Returns:
        A list of dictionaries, each with 'fdcId' and 'description',
        or None if the search fails or yields no results.
    """
    usda_api_key = _get_api_key("USDA_API_KEY", config.USDA_API_KEY)
    if not usda_api_key or usda_api_key == 'YOUR_USDA_API_KEY_PLACEHOLDER':
        logger.warning("USDA API Key not configured. Skipping USDA search.")
        return None

    search_url = f"{config.USDA_API_BASE_URL}/foods/search"
    params = {
        'api_key': usda_api_key,
        'query': item_name,
        'pageSize': 5, # Fetch up to 5 results
        'dataType': 'Foundation,SR Legacy,Survey (FNDDS)' # Broaden search slightly
    }
    try:
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status() # Raise HTTPError for bad responses
        data = response.json()

        candidates = []
        if data.get('foods'):
            for food in data['foods']:
                if food.get('fdcId') and food.get('description'):
                    candidates.append({
                        'fdcId': food['fdcId'],
                        'description': food['description']
                    })

        if candidates:
            logger.info(f"USDA search for '{item_name}' found {len(candidates)} candidates.")
            return candidates
        else:
            logger.info(f"No USDA results found for '{item_name}'")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error searching USDA for '{item_name}': {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding USDA search JSON response for '{item_name}': {e}")
        return None

@lru_cache(maxsize=128) # Cache details more heavily
def _get_usda_nutrition_details(fdc_id: int, quantity_g: float) -> dict | None:
    """Fetches and calculates nutritional details for a specific FDC ID and quantity."""
    logger.info(f"Fetching nutrition details for FDC ID {fdc_id} and quantity {quantity_g}g")
    usda_api_key = _get_api_key("USDA_API_KEY", config.USDA_API_KEY)
    if not usda_api_key or usda_api_key == 'YOUR_USDA_API_KEY_PLACEHOLDER':
        logger.warning("USDA API Key not configured. Skipping USDA details fetch.")
        return None

    details_url = f"{config.USDA_API_BASE_URL}/food/{fdc_id}"
    params = {
        'api_key': usda_api_key,
        # 'format': 'full' # 'abridged' might be sufficient and faster
    }
    try:
        response = requests.get(details_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        # Use 'labelNutrients' for standard Calorie, Protein, Carb, Fat (more reliable format)
        # or fallback to foodNutrients if labelNutrients isn't present
        label_nutrients = data.get('labelNutrients')
        food_nutrients = data.get('foodNutrients', []) # Keep as fallback

        nutrition = {
            'calories': None, 'protein': None, 'carbs': None,
            'fat': None, 'fiber': None, # Initialize as None
            'source': f'USDA (FDC ID: {fdc_id})'
        }

        if label_nutrients:
            logger.debug(f"Using labelNutrients for FDC ID {fdc_id}")
            nutrition['calories'] = label_nutrients.get('calories', {}).get('value')
            nutrition['protein'] = label_nutrients.get('protein', {}).get('value')
            nutrition['carbs'] = label_nutrients.get('carbohydrates', {}).get('value')
            nutrition['fat'] = label_nutrients.get('fat', {}).get('value')
            # Fiber might still be in foodNutrients only
            for food_nutrient in food_nutrients:
                # Ensure nutrient ID exists before accessing it
                nutrient = food_nutrient.get('nutrient', {})
                if nutrient.get('id') == config.NUTRIENT_ID_MAP.get('fiber'): # Use .get for safety
                     # Use .get for amount as well
                     nutrition['fiber'] = food_nutrient.get('amount', 0.0) 
                     break
        else:
            logger.warning(f"labelNutrients not found for FDC ID {fdc_id}. Falling back to foodNutrients.")
            # Fallback to original foodNutrients parsing
            for nutrient_name, nutrient_id in config.NUTRIENT_ID_MAP.items():
                for food_nutrient in food_nutrients:
                    # Ensure nutrient ID exists before accessing it
                    nutrient = food_nutrient.get('nutrient', {})
                    if nutrient.get('id') == nutrient_id:
                        nutrition[nutrient_name] = food_nutrient.get('amount', 0.0)
                        break

        # Calculate based on quantity (values from API are per 100g)
        calculated_nutrition = {} 
        found_any = False
        for key, value in nutrition.items():
            if key == 'source':
                calculated_nutrition[key] = value
                continue
            if value is not None:
                try:
                     calculated_value = (float(value) / 100.0) * quantity_g
                     calculated_nutrition[key] = calculated_value
                     found_any = True
                except (ValueError, TypeError):
                     logger.warning(f"Could not convert value '{value}' for nutrient '{key}' (FDC ID {fdc_id}) to float.")
                     calculated_nutrition[key] = 0.0 # Default to 0 if conversion fails
            else:
                calculated_nutrition[key] = 0.0 # Default nutrients not found to 0


        if found_any:
            logger.info(f"Calculated USDA nutrition for FDC ID {fdc_id} ({quantity_g}g): {calculated_nutrition}")
            return calculated_nutrition
        else:
            logger.warning(f"Could not extract any relevant nutrient values from USDA response for FDC ID {fdc_id}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching USDA details for FDC ID {fdc_id}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding USDA details JSON response for FDC ID {fdc_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing USDA details for FDC ID {fdc_id}: {e}")
        return None 