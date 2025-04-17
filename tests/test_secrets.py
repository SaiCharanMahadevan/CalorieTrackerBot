"""Test script to verify Secret Manager integration."""

import os
import logging
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def test_environment_variables():
    """Test that environment variables are loaded correctly."""
    # Load environment variables from .env file for local testing
    load_dotenv()
    
    # Check if we're running in Cloud Functions
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        logger.info("Running in Cloud Functions environment")
        try:
            from google.cloud import secretmanager
            
            def access_secret_version(secret_id, version_id="latest"):
                """Access the secret from Secret Manager."""
                client = secretmanager.SecretManagerServiceClient()
                name = f"projects/{os.environ.get('GOOGLE_CLOUD_PROJECT')}/secrets/{secret_id}/versions/{version_id}"
                response = client.access_secret_version(request={"name": name})
                return response.payload.data.decode("UTF-8")
            
            # Try to access a secret
            try:
                secret_value = access_secret_version("telegram-bot-token")
                logger.info(f"Successfully accessed secret: {secret_value[:5]}...")
            except Exception as e:
                logger.error(f"Error accessing secret: {e}")
        except ImportError:
            logger.error("google-cloud-secret-manager not available")
    else:
        logger.info("Running in local environment")
    
    # Check environment variables
    env_vars = [
        "TELEGRAM_BOT_TOKEN",
        "GOOGLE_SHEET_ID",
        "WORKSHEET_NAME",
        "GEMINI_API_KEY",
        "USDA_API_KEY",
        "SERVICE_ACCOUNT_JSON"
    ]
    
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            # Mask sensitive values
            if var in ["TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY", "USDA_API_KEY", "SERVICE_ACCOUNT_JSON"]:
                masked_value = f"{value[:5]}...{value[-5:]}" if len(value) > 10 else "***"
            else:
                masked_value = value
            logger.info(f"{var}: {masked_value}")
        else:
            logger.warning(f"{var} not set")

if __name__ == "__main__":
    test_environment_variables() 