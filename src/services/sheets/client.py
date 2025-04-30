"""Handles Google Sheets client authentication and worksheet caching."""

import logging
import json
import threading
from typing import Optional, Dict
import gspread
from google.oauth2 import service_account
from gspread.exceptions import APIError, WorksheetNotFound

# Project imports
from src.config.config import SCOPES
from src.config.config_loader import get_config

logger = logging.getLogger(__name__)

# --- Singleton Client & Worksheet Cache --- 
_gspread_client: Optional[gspread.Client] = None
_gspread_client_lock = threading.Lock()
_worksheet_cache: Dict[tuple[str, str], gspread.Worksheet] = {}
_worksheet_cache_lock = threading.Lock()

def _get_gspread_client() -> gspread.Client:
    """Authenticates and returns a shared gspread Client object using the single service account.
    Raises:
        ValueError: If configuration is missing or invalid.
        RuntimeError: If client initialization fails unexpectedly.
    """
    global _gspread_client
    # Check without lock first for performance
    if _gspread_client is not None:
        return _gspread_client
        
    with _gspread_client_lock:
         # Double-check lock
         if _gspread_client is None:
            logger.info("Initializing shared gspread client...")
            config = None # Ensure config is defined for error handling
            try:
                config = get_config() # Get the singleton config

                if not config.service_account_json_string:
                    logger.critical("Service account JSON string not available in config!")
                    raise ValueError("Missing service account credentials in configuration")

                # Parse the JSON string from the config object
                try:
                    service_account_info = json.loads(config.service_account_json_string)
                except json.JSONDecodeError as e:
                    logger.critical(f"Failed to parse service account JSON from config: {e}")
                    log_snippet = config.service_account_json_string[:50] + "..." if config.service_account_json_string and len(config.service_account_json_string) > 50 else "(empty or None)"
                    logger.critical(f"Problematic JSON string snippet from config: {log_snippet}")
                    raise ValueError("Invalid service account JSON in configuration") from e

                # Use the parsed dictionary for credentials
                creds = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=SCOPES
                )
                _gspread_client = gspread.authorize(creds)
                logger.info("Successfully authorized shared gspread client.")

            except Exception as e:
                logger.error(f"Error initializing shared gspread client: {e}", exc_info=True)
                # Prevent assignment of partially initialized client
                _gspread_client = None # Explicitly reset
                raise # Re-raise exception
                
    # Check again after attempting initialization inside lock
    if _gspread_client is None:
         # Should not happen if exceptions are raised correctly
         raise RuntimeError("Failed to initialize gspread client after lock attempt")
    return _gspread_client

def _get_worksheet(sheet_id: str, worksheet_name: str) -> Optional[gspread.Worksheet]:
    """Gets a specific Worksheet object by ID and name, using caching.
    Returns None if the worksheet cannot be accessed or found.
    """
    cache_key = (sheet_id, worksheet_name)
    
    # Check cache first (without lock for performance)
    cached_ws = _worksheet_cache.get(cache_key)
    if cached_ws is not None:
        logger.debug(f"Returning cached worksheet for key: {cache_key}")
        return cached_ws
        
    # If not in cache, acquire lock to fetch/create
    with _worksheet_cache_lock:
        # Double-check cache inside lock
        cached_ws = _worksheet_cache.get(cache_key)
        if cached_ws is not None:
            logger.debug(f"Returning cached worksheet found inside lock for key: {cache_key}")
            return cached_ws
            
        # Fetch worksheet if still not found
        logger.info(f"Worksheet cache miss for key: {cache_key}. Fetching...")
        try:
            client = _get_gspread_client()
            sheet = client.open_by_key(sheet_id)
            worksheet = sheet.worksheet(worksheet_name)
            # Store in cache
            _worksheet_cache[cache_key] = worksheet
            logger.info(f"Successfully fetched and cached worksheet for key: {cache_key}")
            return worksheet
        except APIError as e:
            logger.error(f"API Error accessing sheet '{sheet_id}', worksheet '{worksheet_name}': {e}", exc_info=True)
            if e.response.status_code == 403:
                 logger.error("Permission denied. Ensure the service account email has editor access to the sheet.")
            return None
        except WorksheetNotFound:
            logger.error(f"Worksheet named '{worksheet_name}' not found in Google Sheet ID '{sheet_id}'.")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting worksheet '{sheet_id}/{worksheet_name}': {e}", exc_info=True)
            return None 