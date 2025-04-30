"""Handles parsing of meal descriptions into structured data."""

import logging
import json
import os
from typing import List, Dict, Any
from src.services.ai_models import AIModelManager
import google.generativeai as genai # Import genai

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def parse_meal_text_with_gemini(meal_text: str) -> List[Dict[str, Any]]:
    """Parse meal text using Gemini API to extract food items and quantities."""
    # Get the model instance for text parsing
    model = AIModelManager.get_model('meal_text')
    
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
    "{meal_text}"

    Output:
    """
    logger.info(f"Sending meal description to Gemini for parsing: {meal_text}")
    try:
        # Define generation config for consistency
        generation_config = genai.types.GenerationConfig(temperature=0.2)
        
        # Add timeout and generation config
        response = model.generate_content(
            prompt, 
            generation_config=generation_config, 
            request_options={"timeout": 30}
        )
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

def parse_meal_image_with_gemini(image_data: bytes) -> List[Dict[str, Any]]:
    """Parse meal image using Gemini API to extract food items and quantities.
    
    Args:
        image_data: The binary image data to analyze.
        
    Returns:
        A list of dictionaries, each with 'item' and 'quantity_g' keys,
        or None if parsing fails.
    """
    logger.info("Sending meal image to Gemini for parsing")
    try:
        # Get the model instance for image parsing
        model = AIModelManager.get_model('meal_vision')
        
        # Create a prompt for the image analysis
        prompt = """
        Analyze this image of food. Identify each distinct food item visible.
        For each item, estimate its quantity in grams (g).
        - Use standard serving sizes as a reference (e.g., a side of broccoli ~ 100g, a chicken breast ~ 150g).
        - Consider the portion size relative to the plate or container.
        - If multiple servings are visible, estimate the total quantity.

        Output ONLY a valid JSON list where each element is an object with two keys:
        1. "item": The name of the food item (string).
        2. "quantity_g": The estimated quantity in grams (numeric).

        Example Output: [{"item": "chicken breast", "quantity_g": 150.0}, {"item": "broccoli", "quantity_g": 100.0}, {"item": "rice", "quantity_g": 180.0}]
        """
        # Define generation config for consistency
        generation_config = genai.types.GenerationConfig(temperature=0.2)

        # Generate content with the image, prompt, and config
        response = model.generate_content(
            [prompt, {"mime_type": "image/jpeg", "data": image_data}],
            generation_config=generation_config,
            request_options={"timeout": 30} # Add timeout here too if needed
        )
        
        # Clean up potential markdown code fences and surrounding text/whitespace
        cleaned_text = response.text.strip().lstrip('```json').rstrip('```').strip()
        logger.debug(f"Raw Gemini vision response: {response.text}")
        logger.debug(f"Cleaned Gemini vision response: {cleaned_text}")
        
        # Parse the JSON response
        parsed_json = json.loads(cleaned_text)
        
        if isinstance(parsed_json, list):
            # Validate structure
            validated_list = []
            all_valid = True
            for item in parsed_json:
                if isinstance(item, dict) and 'item' in item and 'quantity_g' in item and isinstance(item['item'], str) and isinstance(item['quantity_g'], (int, float)):
                    validated_list.append({
                        'item': item['item'],
                        'quantity_g': float(item['quantity_g'])  # Ensure float
                    })
                else:
                    logger.warning(f"Invalid item structure in Gemini vision response: {item}")
                    all_valid = False
            
            if not validated_list:
                logger.error("Gemini vision response parsed, but no valid items found.")
                return None
            if not all_valid:
                logger.warning("Some items in Gemini vision response had invalid structure.")
            
            logger.info(f"Successfully parsed meal image into items: {validated_list}")
            return validated_list
        else:
            logger.error(f"Gemini vision response was not a JSON list: {type(parsed_json)}")
            return None
            
    except json.JSONDecodeError as json_err:
        logger.error(f"Error decoding Gemini vision JSON response: {json_err}. Response text: '{cleaned_text}'")
        return None
    except Exception as e:
        # Catch potential API errors, rate limits, etc.
        logger.error(f"Error calling Gemini vision API or processing response: {e}")
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