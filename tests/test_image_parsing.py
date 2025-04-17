"""Test script for image parsing functionality."""

import os
import sys
import logging
import glob
import json
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configure Gemini API
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    logger.error("GEMINI_API_KEY not found in environment variables")
    sys.exit(1)

genai.configure(api_key=api_key)

def test_image_parsing(image_path):
    """Test the image parsing functionality with a sample image."""
    try:
        # Check if the image file exists
        if not os.path.exists(image_path):
            logger.error(f"Image file not found: {image_path}")
            return False
        
        # Read the image file
        with open(image_path, 'rb') as f:
            image_data = f.read()
        
        # Parse the meal image
        logger.info(f"Testing image parsing with: {image_path}")
        
        # Create a vision model that supports vision - using the latest model
        vision_model = genai.GenerativeModel('gemini-1.5-pro-latest')
        
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
        
        # Generate content with the image - without request_options
        response = vision_model.generate_content(
            [prompt, {"mime_type": "image/jpeg", "data": image_data}]
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
                return False
            if not all_valid:
                logger.warning("Some items in Gemini vision response had invalid structure.")
            
            # Print the parsed items
            logger.info("Successfully parsed meal image:")
            for item in validated_list:
                logger.info(f"  - {item['item']}: {item['quantity_g']}g")
            
            return True
        else:
            logger.error(f"Gemini vision response was not a JSON list: {type(parsed_json)}")
            return False
            
    except json.JSONDecodeError as json_err:
        logger.error(f"Error decoding Gemini vision JSON response: {json_err}. Response text: '{cleaned_text}'")
        return False
    except Exception as e:
        # Catch potential API errors, rate limits, etc.
        logger.error(f"Error testing image parsing: {e}")
        return False

def test_all_images_in_folder(folder_path):
    """Test all images in the specified folder."""
    # Get all image files in the folder
    image_extensions = ['*.jpg', '*.jpeg', '*.png']
    image_files = []
    for ext in image_extensions:
        image_files.extend(glob.glob(os.path.join(folder_path, ext)))
    
    if not image_files:
        logger.error(f"No image files found in {folder_path}")
        return False
    
    logger.info(f"Found {len(image_files)} image files to test")
    
    # Test each image
    success_count = 0
    for image_path in image_files:
        logger.info(f"\n{'='*50}")
        logger.info(f"Testing image: {os.path.basename(image_path)}")
        logger.info(f"{'='*50}")
        
        if test_image_parsing(image_path):
            success_count += 1
    
    # Print summary
    logger.info(f"\n{'='*50}")
    logger.info(f"Test Summary: {success_count}/{len(image_files)} images successfully parsed")
    logger.info(f"{'='*50}")
    
    return success_count > 0

if __name__ == "__main__":
    # Check if a folder path was provided
    if len(sys.argv) > 1:
        folder_path = sys.argv[1]
    else:
        # Use the default test_images folder if none was provided
        folder_path = "tests/test_images"
    
    # Run the test
    success = test_all_images_in_folder(folder_path)
    
    if success:
        logger.info("Image parsing tests completed successfully")
        sys.exit(0)
    else:
        logger.error("Image parsing tests failed")
        sys.exit(1) 