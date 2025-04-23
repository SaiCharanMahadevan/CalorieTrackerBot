import os
import logging
import json
from typing import Optional, List, Dict, Any
import threading # For singleton lock

# --- Import from utils ---
from src.utils import sanitize_token

# Import the schema maps and defaults
from .config import TEMPLATE_SCHEMA_MAP, LEGACY_SCHEMA_MAP, DEFAULT_FIRST_DATA_ROW

logger = logging.getLogger(__name__)

# Singleton instance and lock
_config_instance = None
_config_lock = threading.Lock()

# Default path for the config file if env var is not set
DEFAULT_BOT_CONFIG_PATH = "bot_configs.json"

class AppConfig:
    """Holds the application configuration, loaded once as a singleton."""
    def __init__(self):
        # --- Singleton Check ---
        # This __init__ should ideally only run once via get_config()
        logger.debug("Initializing AppConfig instance...")

        # --- Shared Configuration ---
        self.gemini_api_key: Optional[str] = None
        self.usda_api_key: Optional[str] = None
        self.service_account_json_string: Optional[str] = None # Still load the SA key content

        # --- Multi-Bot Configuration ---
        self.bot_configs: List[Dict[str, Any]] = []
        self._bot_config_map: Dict[str, Dict[str, Any]] = {} # For quick lookup by token

    def _load_shared_config(self):
        """Loads configurations that are shared across all bots."""
        # Load Gemini API Key
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
        if not self.gemini_api_key:
            logger.error("GEMINI_API_KEY not found in environment variables")
            raise ValueError("GEMINI_API_KEY is required")

        # Load USDA API Key
        self.usda_api_key = os.environ.get("USDA_API_KEY")
        if not self.usda_api_key:
            logger.error("USDA_API_KEY not found in environment variables")
            raise ValueError("USDA_API_KEY is required")

        # Load Service Account JSON String from appropriate source
        # Priority: GOOGLE_APPLICATION_CREDENTIALS file path, then SERVICE_ACCOUNT_JSON env var
        gac_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        sa_json_env = os.environ.get("SERVICE_ACCOUNT_JSON")

        if gac_path:
            logger.info(f"GOOGLE_APPLICATION_CREDENTIALS path found: {gac_path}")
            try:
                with open(gac_path, 'r') as f:
                    self.service_account_json_string = f.read()
                logger.info(f"Successfully loaded service account JSON from file: {gac_path}")
            except FileNotFoundError:
                logger.error(f"Service account file specified by GOOGLE_APPLICATION_CREDENTIALS not found: {gac_path}")
                raise ValueError(f"Service account file not found: {gac_path}")
            except Exception as e:
                logger.error(f"Error reading service account file {gac_path}: {e}", exc_info=True)
                raise ValueError(f"Error reading service account file: {gac_path}")
        elif sa_json_env:
            logger.info("Using SERVICE_ACCOUNT_JSON environment variable for service account key.")
            self.service_account_json_string = sa_json_env
        else:
            logger.error("Service Account credentials not found. Set either GOOGLE_APPLICATION_CREDENTIALS (path) or SERVICE_ACCOUNT_JSON (content) environment variable.")
            raise ValueError("Service Account credentials are required")

        if not self.service_account_json_string:
             # This case should ideally be caught above, but as a safeguard:
             logger.error("Failed to load service account JSON string.")
             raise ValueError("Service Account JSON string is missing or empty.")

        logger.info("Shared configuration loaded (API Keys, Service Account)")


    def _load_bot_configs(self):
         """Loads the list of bot configurations from a JSON file."""
         config_path = os.environ.get("BOT_CONFIG_PATH", DEFAULT_BOT_CONFIG_PATH)
         logger.info(f"Attempting to load bot configurations from: {config_path}")

         try:
             with open(config_path, 'r') as f:
                 raw_configs = json.load(f)
         except FileNotFoundError:
             logger.error(f"Bot configuration file not found at: {config_path}")
             # Depending on requirements, maybe allow empty config? For now, raise.
             raise ValueError(f"Bot configuration file not found: {config_path}")
         except json.JSONDecodeError as e:
             logger.error(f"Error decoding JSON from bot config file {config_path}: {e}")
             raise ValueError(f"Invalid JSON in bot configuration file: {config_path}")
         except Exception as e:
             logger.error(f"Error reading bot config file {config_path}: {e}", exc_info=True)
             raise ValueError(f"Could not read bot configuration file: {config_path}")

         if not isinstance(raw_configs, list):
             logger.error(f"Bot configuration file {config_path} should contain a JSON list (array). Found: {type(raw_configs)}")
             raise ValueError("Bot configuration must be a JSON list.")

         self.bot_configs = []
         self._bot_config_map = {}
         seen_tokens = set()

         for i, cfg_dict in enumerate(raw_configs):
             if not isinstance(cfg_dict, dict):
                 logger.warning(f"Item at index {i} in {config_path} is not a JSON object, skipping.")
                 continue

             token = sanitize_token(cfg_dict.get("bot_token"))
             sheet_id = cfg_dict.get("google_sheet_id")
             worksheet_name = cfg_dict.get("worksheet_name", "Sheet1") # Default worksheet name
             allowed_users = cfg_dict.get("allowed_users", []) # Default to empty list (allow all)

             # --- Load and Validate Schema Type --- START
             schema_type = cfg_dict.get("schema_type", "template").lower() # Default to template
             if schema_type not in ["template", "legacy"]:
                 logger.warning(f"Bot config for token {token[:6]}... has invalid 'schema_type': '{schema_type}'. Defaulting to 'template'.")
                 schema_type = "template"

             # --- Determine Column Map and Default First Data Row --- #
             if schema_type == "legacy":
                 column_map = LEGACY_SCHEMA_MAP
                 first_data_row = DEFAULT_FIRST_DATA_ROW["legacy"] # Directly assign default
             else: # Default to template
                 column_map = TEMPLATE_SCHEMA_MAP
                 first_data_row = DEFAULT_FIRST_DATA_ROW["template"] # Directly assign default

             # Validation for required fields (token, sheet_id)
             if not token:
                 logger.warning(f"Bot config at index {i} is missing required 'bot_token'. Skipping.")
                 continue
             if not sheet_id:
                 logger.warning(f"Bot config for token starting with {token[:6]}... (index {i}) is missing required 'google_sheet_id'. Skipping.")
                 continue
             if not isinstance(worksheet_name, str) or not worksheet_name:
                 logger.warning(f"Bot config for token starting with {token[:6]}... (index {i}) has invalid 'worksheet_name'. Using default 'Sheet1'.")
                 worksheet_name = "Sheet1"
             if not isinstance(allowed_users, list):
                 logger.warning(f"Bot config for token starting with {token[:6]}... (index {i}) has invalid 'allowed_users' (must be a list). Defaulting to allow all.")
                 allowed_users = []
             else:
                 # Ensure allowed users are integers
                 valid_users = []
                 for user_id in allowed_users:
                     try:
                         valid_users.append(int(user_id))
                     except (ValueError, TypeError):
                         logger.warning(f"Invalid user ID '{user_id}' in allowed_users for token {token[:6]}... (index {i}). Skipping this user ID.")
                 allowed_users = valid_users

             if token in seen_tokens:
                 logger.warning(f"Duplicate bot_token found: {token[:6]}... (index {i}). Skipping duplicate entry.")
                 continue

             # Store valid config including resolved schema details
             valid_config = {
                 "bot_token": token,
                 "google_sheet_id": sheet_id,
                 "worksheet_name": worksheet_name,
                 "allowed_users": allowed_users,
                 "schema_type": schema_type,
                 "first_data_row": first_data_row,
                 "column_map": column_map # Attach the resolved column map
             }
             self.bot_configs.append(valid_config)
             self._bot_config_map[token] = valid_config
             seen_tokens.add(token)
             logger.info(f"Loaded config for bot {token[:6]}... (Sheet: {sheet_id}, Schema: {schema_type}, StartRow: {first_data_row})")

         if not self.bot_configs:
             logger.warning(f"No valid bot configurations loaded from {config_path}. The application might not function.")
         else:
            logger.info(f"Successfully loaded {len(self.bot_configs)} bot configurations.")

    def load(self):
        """Load all configurations (shared and bot-specific)."""
        logger.info("Loading application configuration...")
        self._load_shared_config()
        self._load_bot_configs()
        logger.info("Configuration loading complete.")

    def get_bot_config_by_token(self, token: str) -> Optional[Dict[str, Any]]:
         """Efficiently retrieves a bot's configuration using its token."""
         # Sanitize input token for lookup consistency
         sanitized_token = sanitize_token(token)
         return self._bot_config_map.get(sanitized_token)


def get_config() -> AppConfig:
    """Gets the singleton AppConfig instance, loading it on first call."""
    global _config_instance
    if _config_instance is None:
        with _config_lock:
            # Double-check locking
            if _config_instance is None:
                logger.info("Creating and loading singleton AppConfig instance.")
                temp_instance = AppConfig()
                try:
                    temp_instance.load()
                    _config_instance = temp_instance
                except Exception as e:
                    logger.critical(f"Failed to load configuration during singleton creation: {e}", exc_info=True)
                    # Prevent partially configured singleton from being assigned
                    raise # Re-raise the exception to halt application startup if config fails
            else:
                 logger.debug("Singleton AppConfig already created by another thread.")
    else:
        logger.debug("Returning existing singleton AppConfig instance.")

    # We check again outside the lock because initialization might have failed
    if _config_instance is None:
         # This state should ideally not be reached if load() raised an exception
         logger.critical("Configuration instance is None after attempting initialization.")
         raise RuntimeError("Application configuration could not be initialized.")

    return _config_instance

# Example of trying to load config at module import (optional, can help catch errors early)
# try:
#     get_config()
#     logger.info("Initial configuration loaded successfully at module import.")
# except Exception as e:
#     # Log critical error, but allow app to continue startup (FastAPI might handle exit)
#     logger.critical(f"Failed to load initial configuration at module import: {e}", exc_info=True) 