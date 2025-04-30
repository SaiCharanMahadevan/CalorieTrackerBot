"""Handles nutrition-related interactions with the Gemini AI model."""

import logging
import json
import re
from functools import lru_cache
from typing import List, Dict, Any # Keep typing for consistency

# Project Imports
from src.config import config # Needed for nutrient map?
from src.services.ai_models import AIModelManager # Import AI Manager

logger = logging.getLogger(__name__)


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

@lru_cache(maxsize=256) # Cache Gemini estimations
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