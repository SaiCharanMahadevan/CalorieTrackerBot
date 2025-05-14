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

@lru_cache(maxsize=256) # Cache Gemini estimations
def _estimate_nutrition_with_gemini(item_name: str, quantity_g: float) -> dict | None:
    """Uses Gemini to estimate nutrition as a fallback."""
    try:
        
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
        
        generation_config_dict = {"temperature": 0.2} # For more factual output
        
        response = AIModelManager.generate_content(
            use_case='nutrition',
            contents=[prompt], 
            config=generation_config_dict
        )
        
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
        cleaned_text_for_error = 'Error before response text was processed'
        try:
            cleaned_text_for_error = cleaned_text
        except NameError:
            pass
        logger.error(f"Error decoding Gemini nutrition JSON response: {json_err}. Response text: '{cleaned_text_for_error}'")
        return None
    except Exception as e:
        logger.error(f"Error calling Gemini API for nutrition estimation: {e}", exc_info=True)
        return None 