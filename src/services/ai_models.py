"""Manages AI model instances for different use cases."""

import logging
from typing import Optional, Any, List, Dict, Union
from google import genai # type: ignore
from src.config.config import GEMINI_API_KEY, GEMINI_MODEL_NAME

logger = logging.getLogger(__name__)

class AIModelManager:
    """Manages AI model instances for different use cases."""
    
    _client: Optional[genai.Client] = None
    _is_initialized = False
    
    @classmethod
    def initialize(cls) -> None:
        """Initialize the AI configuration once."""
        if not cls._is_initialized:
            if not GEMINI_API_KEY or GEMINI_API_KEY == 'YOUR_GEMINI_API_KEY_PLACEHOLDER':
                raise ValueError("Gemini API Key not configured.")
            try:
                # Initialize with the standard client
                cls._client = genai.Client(api_key=GEMINI_API_KEY) 
            except Exception as e:
                logger.error(f"Failed to initialize Google GenAI Client: {e}")
                raise ValueError(f"Failed to initialize Google GenAI Client: {e}") from e
            
            cls._is_initialized = True
            logger.info("Google GenAI Client initialized")

    @classmethod
    def get_client(cls) -> genai.Client:
        """Initializes and returns the shared GenAI client."""
        cls.initialize()
        if cls._client is None:
            raise RuntimeError("GenAI client failed to initialize.")
        return cls._client

    @staticmethod
    def _get_model_config(use_case: str) -> dict:
        """Get the model configuration for a specific use case."""
        configs = {
            'meal_text': {
                'model_name': GEMINI_MODEL_NAME,
                'description': 'Model for parsing meal text descriptions'
            },
            'meal_vision': {
                'model_name': GEMINI_MODEL_NAME,
                'description': 'Model for analyzing meal images'
            },
            'nutrition': {
                'model_name': GEMINI_MODEL_NAME,
                'description': 'Model for nutrition analysis'
            },
            'transcription': {
                'model_name': GEMINI_MODEL_NAME,
                'description': 'Model for transcribing audio'
            }
        }
        
        if use_case not in configs:
            raise ValueError(f"Unknown use case: {use_case}")
        
        return configs[use_case]

    @classmethod
    def get_model_name(cls, use_case: str) -> str:
        """Get the model name for a specific use case."""
        model_config = cls._get_model_config(use_case)
        return model_config['model_name']
    
    @classmethod
    def generate_content(cls, use_case: str, contents: List[Any], **kwargs) -> Any:
        """Generate content using the appropriate model for the use case.
        
        Args:
            use_case: The intended use case (e.g., 'meal_text', 'meal_vision', 'transcription')
            contents: The content to send to the model (text, images, audio, etc.)
            **kwargs: Additional arguments to pass to generate_content

        Returns:
            The response from the model
        """
        cls.initialize()
        if cls._client is None:
            raise RuntimeError("GenAI client is not initialized.")

        model_name = cls.get_model_name(use_case)
        logger.info(f"Generating content with model '{model_name}' for use case '{use_case}'")
        
        # Handle configuration parameters properly
        # Convert legacy parameter names to the format expected by the new SDK
        if 'generation_config' in kwargs:
            logger.info("Converting generation_config to config for new SDK compatibility")
            if 'config' not in kwargs:
                kwargs['config'] = kwargs.pop('generation_config')
            else:
                kwargs['config'].update(kwargs.pop('generation_config'))
                
        # Also handle request_options if present
        if 'request_options' in kwargs:
            logger.info("Moving request_options into config for new SDK compatibility")
            if 'config' not in kwargs:
                kwargs['config'] = {}
            # Move relevant request_options into config
            request_options = kwargs.pop('request_options')
            for key, value in request_options.items():
                kwargs['config'][key] = value

        try:
            # For multimodal content, check if the first item is media content (Part object)
            if (contents and isinstance(contents[0], genai.types.Part) and 
                len(contents) > 1 and isinstance(contents[1], str)):
                # Already in the recommended order (media first, then text)
                logger.debug("Content already in optimal order: media first, then text")
            elif (contents and len(contents) > 1 and isinstance(contents[0], str) and 
                  isinstance(contents[1], genai.types.Part)):
                # Swap to put media first for better performance
                logger.debug("Reordering content to put media first for better performance")
                contents = [contents[1], contents[0]]
                
            return cls._client.models.generate_content(
                model=model_name,
                contents=contents,
                **kwargs
            )
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error calling Gemini API: {error_message}", exc_info=True)
            
            # Provide more specific logging for common errors
            if "parts must not be empty" in error_message.lower():
                logger.error("The 'parts' field in the request content is empty. Make sure all content parts have data.")
            elif "invalid mime type" in error_message.lower():
                logger.error("Invalid MIME type. Check that the media format is supported (e.g., image/jpeg, image/png, audio/mp3).")
            elif "recitation" in error_message.lower():
                logger.error("The model detected potential recitation issues. Consider rephrasing your prompt.")
            elif "400 bad request" in error_message.lower():
                logger.error("Server rejected the request. Check content format and parameters.")
            
            raise

    @classmethod
    def reset(cls) -> None:
        """Reset client. Useful for testing or error recovery."""
        cls._client = None
        cls._is_initialized = False
        logger.info("AI model client reset")

# Usage:
# response = AIModelManager.generate_content('meal_text', ["Analyze this text..."], config={"temperature": 0.2})
# async_response = await AIModelManager.generate_content_async('transcription', [prompt, audio_part]) 