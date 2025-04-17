"""Handles parsing of meal descriptions using Gemini API."""

import google.generativeai as genai
import logging
import json
import config

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

_model = None

def _get_gemini_model():
    """Initializes and returns the Gemini model instance."""
    global _model
    if _model is None:
        try:
            if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == 'YOUR_GEMINI_API_KEY_PLACEHOLDER':
                 raise ValueError("Gemini API Key not configured in config.py or environment variables.")
            genai.configure(api_key=config.GEMINI_API_KEY)
            _model = genai.GenerativeModel(config.GEMINI_MODEL_NAME)
            logger.info(f"Gemini model '{config.GEMINI_MODEL_NAME}' initialized.")
        except Exception as e:
            logger.error(f"Error initializing Gemini model: {e}")
            raise
    return _model

def parse_meal_text_with_gemini(meal_description: str) -> list | None:
    """Parses a natural language meal description into a list of food items with quantities.

    Args:
        meal_description: The user's text input describing the meal.

    Returns:
        A list of dictionaries, each containing 'item' (str) and 'quantity_g' (float),
        or None if parsing fails.
    """
    model = _get_gemini_model()
    if not model:
        return None

    # Enhanced prompt for better structure and unit handling
    prompt = f"""
    Analyze the following meal description. Extract each distinct food item mentioned.
    For each item, determine its quantity and convert it to grams (g).
    - If a unit is provided (e.g., g, oz, kg, ml, cup, piece, slice), convert it to grams.
    - Use standard conversions (e.g., 1 oz = 28.35g, 1 cup of rice ~ 180g, 1 cup of milk ~ 240g, 1 piece/slice might depend on context - estimate reasonably).
    - If no quantity or unit is mentioned for an item, estimate a standard single serving size in grams (e.g., a side of broccoli ~ 100g, a chicken breast ~ 150g).

    Output ONLY a valid JSON list where each element is an object with two keys:
    1.  "item": The name of the food item (string).
    2.  "quantity_g": The estimated quantity in grams (numeric).

    Example Input: "150g chicken breast, 1 cup broccoli, and a slice of bread"
    Example Output: [{{"item": "chicken breast", "quantity_g": 150.0}}, {{"item": "broccoli", "quantity_g": 150.0}}, {{"item": "bread slice", "quantity_g": 30.0}}]

    Input Description:
    "{meal_description}"

    Output:
    """
    logger.info(f"Sending meal description to Gemini for parsing: {meal_description}")
    try:
        response = model.generate_content(prompt)
        # Clean up potential markdown code fences and surrounding text/whitespace
        cleaned_text = response.text.strip().lstrip('```json').rstrip('```').strip()
        logger.debug(f"Raw Gemini response: {response.text}")
        logger.debug(f"Cleaned Gemini response: {cleaned_text}")

        parsed_json = json.loads(cleaned_text)

        if isinstance(parsed_json, list):
             # Validate structure
             validated_list = []
             all_valid = True
             for item in parsed_json:
                 if isinstance(item, dict) and 'item' in item and 'quantity_g' in item and isinstance(item['item'], str) and isinstance(item['quantity_g'], (int, float)):
                     validated_list.append({
                         'item': item['item'],
                         'quantity_g': float(item['quantity_g']) # Ensure float
                     })
                 else:
                     logger.warning(f"Invalid item structure in Gemini response: {item}")
                     all_valid = False
                     # Decide whether to discard the item or the whole response
                     # For now, let's try to keep valid items

             if not validated_list:
                 logger.error("Gemini response parsed, but no valid items found.")
                 return None
             if not all_valid:
                 logger.warning("Some items in Gemini response had invalid structure.")

             logger.info(f"Successfully parsed meal into items: {validated_list}")
             return validated_list
        else:
             logger.error(f"Gemini response was not a JSON list: {type(parsed_json)}")
             return None

    except json.JSONDecodeError as json_err:
        logger.error(f"Error decoding Gemini JSON response: {json_err}. Response text: '{cleaned_text}'")
        return None
    except Exception as e:
        # Catch potential API errors, rate limits, etc.
        logger.error(f"Error calling Gemini API or processing response: {e}")
        return None

# --- Example Usage (for testing) ---
if __name__ == '__main__':
    # Make sure config.py has your GEMINI_API_KEY or it's set as an environment variable
    # Example requires API key setup
    # test_meal = "133g white rice, 1 cup of sambhar and 3 pieces of dairy milk"
    # test_meal_2 = "half an avocado with 2 slices of whole wheat toast and an egg"
    # parsed = parse_meal_text_with_gemini(test_meal_2)
    # if parsed:
    #     print("Parsed Meal Items:")
    #     for item in parsed:
    #         print(f"  - {item['item']}: {item['quantity_g']}g")
    # else:
    #     print("Meal parsing failed.")
    pass # Avoid running example without key setup 