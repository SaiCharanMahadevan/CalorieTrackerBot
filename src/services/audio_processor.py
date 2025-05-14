"""Handles audio transcription using AI models."""

import logging
from typing import Optional
from google import genai  # Import genai for using the types module

# Assuming ai_models initializes the client correctly
from .ai_models import AIModelManager # Function to get the initialized Gemini client

logger = logging.getLogger(__name__)

async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Optional[str]:
    """
    Transcribes the given audio bytes using the configured Gemini model.

    Args:
        audio_bytes: The raw bytes of the audio file.
        mime_type: The MIME type of the audio file (e.g., "audio/ogg", "audio/mp3").

    Returns:
        The transcribed text as a string, or None if transcription fails.
    """
    logger.info(f"Attempting to transcribe audio ({len(audio_bytes)} bytes, type: {mime_type})...")
    try:
        # Define the refined prompt for accurate transcription
        prompt = """
        Your sole task is high-fidelity audio transcription.
        Accurately transcribe the spoken words in the provided audio file.
        Capture all details precisely as spoken, including specific food items, quantities, units (e.g., grams, ounces, cups), brand names, and descriptive terms.
        Output ONLY the transcribed text, with no additional commentary, interpretation, formatting (unless naturally part of the speech), or summarization.
        Focus on converting the speech to text as literally as possible.
        """

        # Prepare the audio content using the proper SDK types
        audio_part = genai.types.Part.from_bytes(
            data=audio_bytes,
            mime_type=mime_type
        )

        # For multimodal content, the Google GenAI documentation recommends 
        # placing the media content first for better results - place audio before prompt
        contents = [audio_part, prompt]

        # Generate content using the prompt and audio
        response = AIModelManager.generate_content(
            use_case='transcription',
            contents=contents,
            config={"temperature": 0.2}
        )

        # Check and extract the transcribed text
        if response and response.text:
            transcript = response.text.strip()
            logger.info(f"Successfully transcribed audio. Transcript length: {len(transcript)}")
            logger.debug(f"Transcript snippet: {transcript[:100]}...")
            return transcript
        else:
            logger.warning("Transcription response was empty or invalid.")
            if response and hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                 logger.warning(f"Prompt Feedback: {response.prompt_feedback}")
            # Log candidate information if available for debugging
            if response and hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'finish_reason'):
                         logger.warning(f"Candidate Finish Reason: {candidate.finish_reason}")
                    if hasattr(candidate, 'safety_ratings'):
                         logger.warning(f"Candidate Safety Ratings: {candidate.safety_ratings}")
            return None

    except Exception as e:
        logger.error(f"Error during audio transcription: {e}", exc_info=True)
        return None 