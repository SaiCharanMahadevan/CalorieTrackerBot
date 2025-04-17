"""Handles fetching nutritional information from external APIs."""

import requests
import logging
import os
import json
import re # For parsing Gemini's ID choice
from typing import List, Dict, Any
from src.config import config
from src.services.ai_models import AIModelManager

logger = logging.getLogger(__name__)

def _get_api_key(key_name, config_value):
    """Get API key from environment variables or config."""
    return os.environ.get(key_name, config_value)

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

def _choose_best_usda_match(original_query: str, candidates: list[dict]) -> int | None:
    """Uses Gemini to select the best FDC ID from multiple USDA candidates.

    Args:
        original_query: The user's original search term for the food item.
        candidates: A list of candidate dicts [{'fdcId': ..., 'description': ...}].

    Returns:
        The chosen FDC ID, or None if a choice cannot be made.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        logger.info(f"Only one USDA candidate found for '{original_query}', selecting FDC ID: {candidates[0]['fdcId']}")
        return candidates[0]['fdcId']

    # Get the nutrition model instance
    model = AIModelManager.get_model('nutrition')

    # Format candidates for the prompt
    candidates_text = "\n".join([
        f"(ID: {c['fdcId']}) {c['description']}"
        for c in candidates
    ])

    prompt = f"""Original User Query: "{original_query}"

Which of the following USDA food descriptions is the most common or likely match for the user query? Consider common preparations and types unless specified otherwise.
Please return ONLY the corresponding FDC ID number from the list below. Do not include any other text or explanation.

Candidates:
{candidates_text}

Chosen FDC ID:"""

    logger.info(f"Asking Gemini to choose best USDA match for '{original_query}' from {len(candidates)} candidates.")
    try:
        # Add timeout to prevent hanging
        response = model.generate_content(prompt, request_options={"timeout": 30})  # 30 second timeout
        response_text = response.text.strip()
        logger.debug(f"Gemini selection response for '{original_query}': '{response_text}'")

        # Extract the numeric ID from the response
        match = re.search(r'\b(\d+)\b', response_text)
        if match:
            chosen_id = int(match.group(1))
            # Verify the chosen ID is actually one of the candidates
            candidate_ids = {c['fdcId'] for c in candidates}
            if chosen_id in candidate_ids:
                logger.info(f"Gemini chose FDC ID: {chosen_id} for query '{original_query}'")
                return chosen_id
            else:
                logger.warning(f"Gemini returned ID {chosen_id} which was not in the candidate list for '{original_query}'. Defaulting to first candidate: {candidates[0]['fdcId']}")
                return candidates[0]['fdcId']
        else:
            logger.warning(f"Could not parse FDC ID from Gemini response: '{response_text}'. Defaulting to first candidate: {candidates[0]['fdcId']}")
            return candidates[0]['fdcId']

    except Exception as e:
        logger.error(f"Error calling Gemini API for candidate selection: {e}")
        logger.warning(f"Defaulting to first USDA candidate due to Gemini error: {candidates[0]['fdcId']}")
        return candidates[0]['fdcId']

def _get_usda_nutrition_details(fdc_id: int, quantity_g: float) -> dict | None:
    """Fetches and calculates nutritional details for a specific FDC ID and quantity."""
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
                if food_nutrient.get('nutrient', {}).get('id') == config.NUTRIENT_ID_MAP['fiber']:
                     nutrition['fiber'] = food_nutrient.get('amount', 0.0)
                     break
        else:
            logger.warning(f"labelNutrients not found for FDC ID {fdc_id}. Falling back to foodNutrients.")
            # Fallback to original foodNutrients parsing
            for nutrient_name, nutrient_id in config.NUTRIENT_ID_MAP.items():
                for food_nutrient in food_nutrients:
                    if food_nutrient.get('nutrient', {}).get('id') == nutrient_id:
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

def _estimate_nutrition_with_gemini(item_name: str, quantity_g: float) -> dict | None:
    """Uses Gemini to estimate nutrition as a fallback."""
    # Get the nutrition model instance
    model = AIModelManager.get_model('nutrition')
    
    prompt = f"""
    Estimate the nutritional information (calories, protein, carbohydrates, fat, and fiber) for the following food item and quantity. Provide values per the specified quantity, not per 100g.

    Food Item: "{item_name}"
    Quantity: {quantity_g} grams

    Output ONLY a valid JSON object with the following numeric keys:
    - "calories"
    - "protein"
    - "carbs"
    - "fat"
    - "fiber"

    Example Output: {{"calories": 250.0, "protein": 10.5, "carbs": 30.0, "fat": 8.2, "fiber": 3.1}}
    
    Output:
    """
    logger.info(f"Requesting Gemini nutrition estimation for '{item_name}' ({quantity_g}g)")
    try:
        # Add timeout to prevent hanging
        response = model.generate_content(prompt, request_options={"timeout": 30})  # 30 second timeout
        # Clean up potential markdown code fences and surrounding text/whitespace
        cleaned_text = response.text.strip().lstrip('```json').rstrip('```').strip()
        logger.debug(f"Raw Gemini response: {response.text}")
        logger.debug(f"Cleaned Gemini response: {cleaned_text}")
        
        parsed_json = json.loads(cleaned_text)

        if isinstance(parsed_json, dict):
            required_keys = {'calories', 'protein', 'carbs', 'fat', 'fiber'}
            if required_keys.issubset(parsed_json.keys()) and all(isinstance(parsed_json[k], (int, float)) for k in required_keys):
                nutrition = {k: float(parsed_json[k]) for k in required_keys}
                nutrition['source'] = 'Gemini (Estimate)'
                logger.info(f"Received Gemini nutrition estimate for '{item_name}': {nutrition}")
                return nutrition
            else:
                logger.warning(f"Gemini nutrition response structure is incorrect: {parsed_json}")
                return None
        else:
            logger.error(f"Gemini nutrition response was not a JSON object: {type(parsed_json)}")
            return None
        
    except json.JSONDecodeError as json_err:
        logger.error(f"Error decoding Gemini nutrition JSON response: {json_err}. Response text: '{cleaned_text}'")
        return None
    except Exception as e:
        logger.error(f"Error calling Gemini API for nutrition estimation: {e}")
        return None

def get_nutrition_for_items(items: List[Dict[str, Any]]) -> Dict[str, float] | None:
    """Gets aggregated nutritional info for a list of parsed meal items.
       Uses Gemini to help select the best USDA match if multiple candidates exist.
    """
    total_nutrition = {
        'calories': 0.0, 'protein': 0.0, 'carbs': 0.0,
        'fat': 0.0, 'fiber': 0.0,
        'items_processed': [], 'items_failed': []
    }
    success = False

    if not items:
        logger.warning("Received empty items list for nutrition lookup.")
        return None

    for item in items:
        item_name = item.get('item')
        quantity_g = item.get('quantity_g')

        if not item_name or quantity_g is None or quantity_g <= 0:
            logger.warning(f"Skipping invalid item: {item}")
            total_nutrition['items_failed'].append(item_name or "Unknown Item")
            continue

        logger.info(f"--- Processing nutrition for: {item_name} ({quantity_g}g) ---")
        nutrition_data = None
        best_fdc_id = None

        # 1. Try USDA Search
        usda_candidates = _search_usda_food(item_name)

        # 2. If candidates found, choose the best one (using Gemini if multiple)
        if usda_candidates:
            best_fdc_id = _choose_best_usda_match(item_name, usda_candidates)

        # 3. If a best FDC ID was chosen, get its details
        if best_fdc_id:
            nutrition_data = _get_usda_nutrition_details(best_fdc_id, quantity_g)
            if not nutrition_data:
                 logger.warning(f"Could not get details for chosen FDC ID {best_fdc_id} for '{item_name}'. Proceeding to Gemini estimate.")

        # 4. Fallback to Gemini Estimation if USDA search/selection/details failed
        if not nutrition_data:
            if usda_candidates:
                 logger.info(f"USDA lookup/selection failed for '{item_name}'. Trying Gemini estimation.")
            else:
                 logger.info(f"No USDA results for '{item_name}'. Trying Gemini estimation.")
            nutrition_data = _estimate_nutrition_with_gemini(item_name, quantity_g)

        # 5. Aggregate results
        if nutrition_data:
            # Use get() with default 0.0 in case a nutrient was None
            total_nutrition['calories'] += nutrition_data.get('calories', 0.0) or 0.0
            total_nutrition['protein'] += nutrition_data.get('protein', 0.0) or 0.0
            total_nutrition['carbs'] += nutrition_data.get('carbs', 0.0) or 0.0
            total_nutrition['fat'] += nutrition_data.get('fat', 0.0) or 0.0
            total_nutrition['fiber'] += nutrition_data.get('fiber', 0.0) or 0.0
            total_nutrition['items_processed'].append(f"{item_name} ({nutrition_data.get('source', 'Unknown Source')})")
            success = True # Mark as successful if at least one item is processed
            logger.info(f"Successfully processed '{item_name}'. Source: {nutrition_data.get('source', 'Unknown Source')}")
        else:
            logger.warning(f"Could not retrieve or estimate nutrition for '{item_name}'.")
            total_nutrition['items_failed'].append(item_name)

    if success:
        # Clean up unnecessary keys before returning
        aggregated_result = {k: v for k, v in total_nutrition.items() if k not in ['items_processed', 'items_failed']}

        # Round the final aggregated values to the nearest integer
        final_rounded_result = {
            key: round(value) if isinstance(value, (float, int)) else value
            for key, value in aggregated_result.items()
        }

        logger.info(f"Aggregated Nutrition (Rounded): {final_rounded_result}")
        logger.info(f"Processed Items: {total_nutrition['items_processed']}")
        if total_nutrition['items_failed']:
            logger.warning(f"Failed Items: {total_nutrition['items_failed']}")
        return final_rounded_result # Return the rounded dictionary
    else:
        logger.error("Failed to process nutrition for all items in the list.")
        return None

# --- Example Usage (for testing) ---
if __name__ == '__main__':
    # Requires API keys in config.py or environment variables
    # test_items = [
    #     {'item': 'cooked white rice', 'quantity_g': 133.0},
    #     #{'item': 'raw apple', 'quantity_g': 150.0},
    #     #{'item': 'peanut butter smooth', 'quantity_g': 30.0},
    #     #{'item': 'blbxxyyz non existent food', 'quantity_g': 100.0} # Test failure
    # ]
    # nutrition = get_nutrition_for_items(test_items)
    # if nutrition:
    #     print("\n--- Total Meal Nutrition ---")
    #     for key, value in nutrition.items():
    #         print(f"  {key.capitalize()}: {value:.1f}") # Adjust formatting as needed
    # else:
    #     print("\nFailed to get nutrition for the meal.")
    pass # Avoid running example without key setup 