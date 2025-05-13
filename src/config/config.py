"""Configuration settings for the Calorie Tracker Bot."""

import os
from dotenv import load_dotenv # Uncomment for local development with .env file

load_dotenv() # Uncomment for local development

# --- Telegram Configuration ---
# Replace with your actual Telegram Bot Token (obtained from BotFather)
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN_PLACEHOLDER')

# --- Google Sheets Configuration ---
# Replace with the ID of your Google Sheet
# (Found in the URL: docs.google.com/spreadsheets/d/SHEET_ID/edit)
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID', 'YOUR_GOOGLE_SHEET_ID_PLACEHOLDER')
# Name of the worksheet within the Google Sheet
WORKSHEET_NAME = os.getenv('WORKSHEET_NAME', 'Sheet1') # Adjust if your sheet name is different
# Path to your Google Cloud Service Account JSON key file
# IMPORTANT: Store this file securely and DO NOT commit it to version control.
# Consider using GCP Secret Manager for production deployments.
SERVICE_ACCOUNT_JSON = os.getenv('SERVICE_ACCOUNT_JSON', 'path/to/your/service_account.json')
# Google API Scopes needed
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

# --- Google Gemini API Configuration ---
# Replace with your actual Gemini API Key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'YOUR_GEMINI_API_KEY_PLACEHOLDER')
GEMINI_MODEL_NAME = os.getenv('GEMINI_MODEL_NAME', 'gemini-2.0-flash') # Do not change this

# --- Schema-Specific Column Mappings --- #
# Standardized Keys used by the bot logic
# Values are the 0-based indices for each schema type

TEMPLATE_SCHEMA_MAP = {
    'DATE_COL_IDX': 0,
    'WEIGHT_COL_IDX': 1,
    'WEIGHT_TIME_COL_IDX': 2,
    'SLEEP_HOURS_COL_IDX': 3,
    'SLEEP_QUALITY_COL_IDX': 4,
    'STEPS_COL_IDX': 5,
    'CARDIO_COL_IDX': 6,
    'TRAINING_COL_IDX': 7,
    'ENERGY_COL_IDX': 8,
    'MOOD_COL_IDX': 9,
    'SATIETY_COL_IDX': 10,
    'DIGESTION_COL_IDX': 11,
    'CALORIES_COL_IDX': 12,
    'PROTEIN_COL_IDX': 13,
    'CARBS_COL_IDX': 14,
    'FAT_COL_IDX': 15,
    'FIBER_COL_IDX': 16,
    'WATER_COL_IDX': 17
}

LEGACY_SCHEMA_MAP = {
    'DATE_COL_IDX': 1,       # Column B
    'WEIGHT_COL_IDX': 2,     # Column C
    'WEIGHT_TIME_COL_IDX': 3, # Column D
    'SLEEP_HOURS_COL_IDX': 4, # Column E (was SLEEP_COL_IDX)
    'SLEEP_QUALITY_COL_IDX': 5, # Column F
    'STEPS_COL_IDX': 6,      # Column G
    'CARDIO_COL_IDX': 7,     # Column H
    'TRAINING_COL_IDX': 8,   # Column I
    'ENERGY_COL_IDX': 9,     # Column J
    'MOOD_COL_IDX': 10,      # Column K
    'SATIETY_COL_IDX': 11,   # Column L
    'DIGESTION_COL_IDX': 12, # Column M
    'CALORIES_COL_IDX': 13,  # Column N
    'PROTEIN_COL_IDX': 14,   # Column O
    'CARBS_COL_IDX': 15,     # Column P
    'FAT_COL_IDX': 16,       # Column Q
    'FIBER_COL_IDX': 17,     # Column R
    'WATER_COL_IDX': 18      # Column S (was H2O_COL_IDX)
}

# Default starting row index (0-based) for each schema type
DEFAULT_FIRST_DATA_ROW = {
    'template': 1, # Row 2 in sheets
    'legacy': 9    # Row 10 in sheets
}

# --- Global Placeholders (No longer used directly for indices) ---
# These constants are now resolved dynamically per bot based on schema_type
# DATE_COL_IDX = 0 # REMOVED
# ... other _COL_IDX removed ...
# FIRST_DATA_ROW_IDX = 1 # REMOVED

# Dictionary to map conversational choices to metric details
# This now primarily defines the *logic* (prompt, type, number of values)
# The actual column indices are retrieved dynamically based on the bot's schema
LOGGING_CHOICES_MAP = {
    'wellness': {
        'prompt': (
            "Log Wellness (Energy Mood Satiety Digestion) - space-separated, e.g., 8 9 7 3\n\n"
            "Scales (1-10, Digestion 0-7):\n"
            "⚡️ Energy: 1=Zombie <-> 10=Buzzin'\n"
            "😊 Mood:   1=I Hate Life <-> 10=I Love Life\n"
            "🍴 Satiety: 1=Ravenous <-> 10=Satisfied\n"
            "💩 Digestion: 0=No Stool, 1-7=Bristol Chart"
        ),
        'type': 'numeric_multi',
        'metrics': ['ENERGY_COL_IDX', 'MOOD_COL_IDX', 'SATIETY_COL_IDX', 'DIGESTION_COL_IDX'], # Standardized keys
        'num_values': 4
    },
    'sleep': {
        'prompt': (
            "Log Sleep (Hours Quality) - space-separated, e.g., 7.5 8\n\n"
            "Scale (1-10):\n"
            "😴 Quality: 1=Restless <-> 10=Well Rested"
        ),
        'type': 'numeric_multi',
        'metrics': ['SLEEP_HOURS_COL_IDX', 'SLEEP_QUALITY_COL_IDX'], # Standardized keys
        'num_values': 2
    },
    'weight': {
        'prompt': "Weight [Time] (e.g., 85.5 0930 or just 85.5):",
        'type': 'weight_time',
        'metrics': ['WEIGHT_COL_IDX', 'WEIGHT_TIME_COL_IDX'], # Standardized keys
        'num_values': 1 # Base value is weight
    },
    'steps': {
        'prompt': "Steps:",
        'type': 'numeric_single',
        'metrics': ['STEPS_COL_IDX'], # Standardized key
        'num_values': 1
    },
    'cardio': {
        'prompt': "Cardio details (text):",
        'type': 'text_single',
        'metrics': ['CARDIO_COL_IDX'], # Standardized key
        'num_values': 1
    },
    'training': {
        'prompt': "Training details (text):",
        'type': 'text_single',
        'metrics': ['TRAINING_COL_IDX'], # Standardized key
        'num_values': 1
    },
    'water': {
        'prompt': "Water Intake (e.g., glasses, L):",
        'type': 'numeric_single',
        'metrics': ['WATER_COL_IDX'], # Standardized key
        'num_values': 1
    },
} 