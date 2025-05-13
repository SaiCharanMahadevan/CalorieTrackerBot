"""Main API for the nutrition service, orchestrating calls to sub-modules."""

import logging
from typing import List, Dict, Any

from .gemini_handler import _estimate_nutrition_with_gemini

logger = logging.getLogger(__name__)

def get_nutrition_for_items(items: List[Dict[str, Any]]) -> Dict[str, float] | None:
    """Gets aggregated nutritional info for a list of parsed meal items.
       Uses Gemini handler to estimate data.
    """
    total_nutrition = {
        'calories': 0.0, 'protein': 0.0, 'carbs': 0.0,
        'fat': 0.0, 'fiber': 0.0,
        'items_processed': [], 'items_failed': []
    }
    success = False

    if not items:
        logger.warning("Received empty items list for nutrition lookup.")
        return None

    for item in items:
        item_name = item.get('item')
        quantity_g = item.get('quantity_g')

        if not item_name or quantity_g is None or quantity_g <= 0:
            logger.warning(f"Skipping invalid item: {item}")
            total_nutrition['items_failed'].append(item_name or "Unknown Item")
            continue

        logger.info(f"--- Processing nutrition for: {item_name} ({quantity_g}g) ---")
        logger.info(f"Using Gemini estimation for '{item_name}'.")
        nutrition_data = _estimate_nutrition_with_gemini(item_name, quantity_g)

        if nutrition_data:
            total_nutrition['calories'] += nutrition_data.get('calories', 0.0) or 0.0
            total_nutrition['protein'] += nutrition_data.get('protein', 0.0) or 0.0
            total_nutrition['carbs'] += nutrition_data.get('carbs', 0.0) or 0.0
            total_nutrition['fat'] += nutrition_data.get('fat', 0.0) or 0.0
            total_nutrition['fiber'] += nutrition_data.get('fiber', 0.0) or 0.0
            total_nutrition['items_processed'].append(f"{item_name} ({nutrition_data.get('source', 'Unknown Source')})")
            success = True
            logger.info(f"Successfully processed '{item_name}'. Source: {nutrition_data.get('source', 'Unknown Source')}")
        else:
            logger.warning(f"Could not retrieve or estimate nutrition for '{item_name}'.")
            total_nutrition['items_failed'].append(item_name)

    if success:
        aggregated_result = {k: v for k, v in total_nutrition.items() if k not in ['items_processed', 'items_failed']}
        final_rounded_result = {
            key: round(value) if isinstance(value, (float, int)) else value
            for key, value in aggregated_result.items()
        }
        logger.info(f"Aggregated Nutrition (Rounded): {final_rounded_result}")
        logger.info(f"Processed Items: {total_nutrition['items_processed']}")
        if total_nutrition['items_failed']:
            logger.warning(f"Failed Items: {total_nutrition['items_failed']}")
        return final_rounded_result
    else:
        logger.error("Failed to process nutrition for all items in the list.")
        return None 