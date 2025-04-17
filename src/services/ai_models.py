"""Manages AI model instances for different use cases."""

import logging
from typing import Optional
import google.generativeai as genai
from src.config.config import GEMINI_API_KEY, GEMINI_MODEL_NAME

logger = logging.getLogger(__name__)

class AIModelManager:
    """Manages AI model instances for different use cases."""
    
    _instances = {}  # Stores model instances by use case
    _is_initialized = False
    
    @classmethod
    def initialize(cls) -> None:
        """Initialize the AI configuration once."""
        if not cls._is_initialized:
            if not GEMINI_API_KEY or GEMINI_API_KEY == 'YOUR_GEMINI_API_KEY_PLACEHOLDER':
                raise ValueError("Gemini API Key not configured.")
            genai.configure(api_key=GEMINI_API_KEY)
            cls._is_initialized = True
            logger.info("AI configuration initialized")
    
    @classmethod
    def get_model(cls, use_case: str) -> genai.GenerativeModel:
        """Get or create a model instance for a specific use case.
        
        Args:
            use_case: The intended use case (e.g., 'meal_text', 'meal_vision', 'nutrition')
        
        Returns:
            A GenerativeModel instance configured for the use case
        """
        cls.initialize()
        
        if use_case not in cls._instances:
            model_config = cls._get_model_config(use_case)
            cls._instances[use_case] = genai.GenerativeModel(model_config['model_name'])
            logger.info(f"Created new AI model instance for use case: {use_case}")
        
        return cls._instances[use_case]
    
    @staticmethod
    def _get_model_config(use_case: str) -> dict:
        """Get the model configuration for a specific use case."""
        configs = {
            'meal_text': {
                'model_name': GEMINI_MODEL_NAME,
                'description': 'Model for parsing meal text descriptions'
            },
            'meal_vision': {
                'model_name': GEMINI_MODEL_NAME,  # Vision-capable model
                'description': 'Model for analyzing meal images'
            },
            'nutrition': {
                'model_name': GEMINI_MODEL_NAME,
                'description': 'Model for nutrition analysis'
            }
        }
        
        if use_case not in configs:
            raise ValueError(f"Unknown use case: {use_case}")
        
        return configs[use_case]
    
    @classmethod
    def reset(cls) -> None:
        """Reset all model instances. Useful for testing or error recovery."""
        cls._instances.clear()
        cls._is_initialized = False
        logger.info("AI model instances reset") 