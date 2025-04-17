"""Test script for Gemini API usage."""

import os
import sys
import logging
from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def test_text_model():
    """Test the text model API."""
    try:
        # Get API key from environment
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            logger.error("GEMINI_API_KEY not found in environment variables")
            return False
        
        # Configure Gemini API
        genai.configure(api_key=api_key)
        
        # Create a model
        model = genai.GenerativeModel('gemini-1.5-pro')
        
        # Test with request_options
        logger.info("Testing text model with request_options")
        response = model.generate_content(
            "Hello, how are you?",
            request_options={"timeout": 30}
        )
        logger.info(f"Response: {response.text}")
        
        # Test without request_options
        logger.info("Testing text model without request_options")
        response = model.generate_content("Hello, how are you?")
        logger.info(f"Response: {response.text}")
        
        return True
    except Exception as e:
        logger.error(f"Error testing text model: {e}")
        return False

def test_vision_model():
    """Test the vision model API."""
    try:
        # Get API key from environment
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            logger.error("GEMINI_API_KEY not found in environment variables")
            return False
        
        # Configure Gemini API
        genai.configure(api_key=api_key)
        
        # Create a vision model - using the latest model
        vision_model = genai.GenerativeModel('gemini-1.5-pro-latest')
        
        # Test with request_options - this should fail
        logger.info("Testing vision model with request_options")
        try:
            response = vision_model.generate_content(
                ["Describe this image", {"mime_type": "image/jpeg", "data": b"fake_image_data"}],
                request_options={"timeout": 30}
            )
            logger.info(f"Response: {response.text}")
        except Exception as e:
            logger.error(f"Error with request_options: {e}")
        
        # Test without request_options - this should work
        logger.info("Testing vision model without request_options")
        try:
            response = vision_model.generate_content(
                ["Describe this image", {"mime_type": "image/jpeg", "data": b"fake_image_data"}]
            )
            logger.info(f"Response: {response.text}")
            return True
        except Exception as e:
            logger.error(f"Error without request_options: {e}")
            return False
        
    except Exception as e:
        logger.error(f"Error testing vision model: {e}")
        return False

if __name__ == "__main__":
    logger.info("Testing Gemini API")
    
    # Test text model
    logger.info("\n=== Testing Text Model ===")
    text_success = test_text_model()
    
    # Test vision model
    logger.info("\n=== Testing Vision Model ===")
    vision_success = test_vision_model()
    
    if text_success and vision_success:
        logger.info("All tests completed successfully")
        sys.exit(0)
    else:
        logger.error("Some tests failed")
        sys.exit(1) 