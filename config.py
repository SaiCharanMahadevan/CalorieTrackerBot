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
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', 'path/to/your/service_account.json')
# Google API Scopes needed
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

# --- Google Gemini API Configuration ---
# Replace with your actual Gemini API Key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'YOUR_GEMINI_API_KEY_PLACEHOLDER')
GEMINI_MODEL_NAME = os.getenv('GEMINI_MODEL_NAME', 'gemini-2.5-pro-exp-03-25') # Do not change this

# --- USDA FoodData Central API Configuration ---
# Replace with your actual USDA API Key (obtainable from api.nal.usda.gov)
USDA_API_KEY = os.getenv('USDA_API_KEY', 'YOUR_USDA_API_KEY_PLACEHOLDER')
USDA_API_BASE_URL = "https://api.nal.usda.gov/fdc/v1"

# --- Google Sheets Column Mapping (0-based index for code logic) ---
# Adjust these if your sheet structure differs from the provided example
DATE_COL_IDX = 1       # Column B
WEIGHT_COL_IDX = 2     # Column C
SLEEP_COL_IDX = 4      # Column E
SLEEP_QUALITY_COL_IDX = 5 # Column F
STEPS_COL_IDX = 6      # Column G
ENERGY_COL_IDX = 9     # Column J
MOOD_COL_IDX = 10      # Column K
SATIETY_COL_IDX = 11   # Column L
DIGESTION_COL_IDX = 12 # Column M
CALORIES_COL_IDX = 13  # Column N
PROTEIN_COL_IDX = 14   # Column O
CARBS_COL_IDX = 15     # Column P
FAT_COL_IDX = 16       # Column Q
FIBER_COL_IDX = 17     # Column R

# Row index (0-based) where the actual data starts (below headers)
FIRST_DATA_ROW_IDX = 9 # Row 10 in Google Sheets

# Dictionary to map user-friendly metric names to column indices
METRIC_COLUMN_MAP = {
    'weight': WEIGHT_COL_IDX,
    'sleep': SLEEP_COL_IDX,
    'sleep quality': SLEEP_QUALITY_COL_IDX,
    'steps': STEPS_COL_IDX,
    'energy': ENERGY_COL_IDX,
    'mood': MOOD_COL_IDX,
    'satiety': SATIETY_COL_IDX,
    'digestion': DIGESTION_COL_IDX,
    # 'calories': CALORIES_COL_IDX, # Handled separately by add_nutrition
    # 'protein': PROTEIN_COL_IDX,
    # 'carbs': CARBS_COL_IDX,
    # 'fat': FAT_COL_IDX,
    # 'fiber': FIBER_COL_IDX,
}

# Nutrient IDs for USDA API (Common ones, verify if needed)
# These might vary slightly depending on the exact food data type returned by USDA
NUTRIENT_ID_MAP = {
    'calories': 1008, # Energy in kcal
    'protein': 1003,  # Protein
    'carbs': 1005,    # Carbohydrate, by difference
    'fat': 1004,      # Total lipid (fat)
    'fiber': 1079     # Fiber, total dietary
} 