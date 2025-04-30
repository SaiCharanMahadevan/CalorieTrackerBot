"""Main API for the nutrition service, orchestrating calls to sub-modules."""

import logging
from typing import List, Dict, Any

# Local Imports from submodules
from .usda_handler import _search_usda_food, _get_usda_nutrition_details
from .gemini_handler import _choose_best_usda_match, _estimate_nutrition_with_gemini

logger = logging.getLogger(__name__)

def get_nutrition_for_items(items: List[Dict[str, Any]]) -> Dict[str, float] | None:
    """Gets aggregated nutritional info for a list of parsed meal items.
       Uses USDA and Gemini handlers to fetch and estimate data.
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
        nutrition_data = None
        best_fdc_id = None

        # 1. Try USDA Search (from usda_handler)
        usda_candidates = _search_usda_food(item_name)

        # 2. If candidates found, choose the best one (using gemini_handler)
        if usda_candidates:
            best_fdc_id = _choose_best_usda_match(item_name, usda_candidates)

        # 3. If a best FDC ID was chosen, get its details (from usda_handler)
        if best_fdc_id:
            nutrition_data = _get_usda_nutrition_details(best_fdc_id, quantity_g)
            if not nutrition_data:
                 logger.warning(f"Could not get details for chosen FDC ID {best_fdc_id} for '{item_name}'. Proceeding to Gemini estimate.")

        # 4. Fallback to Gemini Estimation if needed (from gemini_handler)
        if not nutrition_data:
            if usda_candidates:
                 logger.info(f"USDA lookup/selection failed for '{item_name}'. Trying Gemini estimation.")
            else:
                 logger.info(f"No USDA results for '{item_name}'. Trying Gemini estimation.")
            nutrition_data = _estimate_nutrition_with_gemini(item_name, quantity_g)

        # 5. Aggregate results
        if nutrition_data:
            # Use get() with default 0.0 in case a nutrient was None
            total_nutrition['calories'] += nutrition_data.get('calories', 0.0) or 0.0
            total_nutrition['protein'] += nutrition_data.get('protein', 0.0) or 0.0
            total_nutrition['carbs'] += nutrition_data.get('carbs', 0.0) or 0.0
            total_nutrition['fat'] += nutrition_data.get('fat', 0.0) or 0.0
            total_nutrition['fiber'] += nutrition_data.get('fiber', 0.0) or 0.0
            total_nutrition['items_processed'].append(f"{item_name} ({nutrition_data.get('source', 'Unknown Source')})")
            success = True # Mark as successful if at least one item is processed
            logger.info(f"Successfully processed '{item_name}'. Source: {nutrition_data.get('source', 'Unknown Source')}")
        else:
            logger.warning(f"Could not retrieve or estimate nutrition for '{item_name}'.")
            total_nutrition['items_failed'].append(item_name)

    if success:
        # Clean up unnecessary keys before returning
        aggregated_result = {k: v for k, v in total_nutrition.items() if k not in ['items_processed', 'items_failed']}

        # Round the final aggregated values to the nearest integer
        final_rounded_result = {
            key: round(value) if isinstance(value, (float, int)) else value
            for key, value in aggregated_result.items()
        }

        logger.info(f"Aggregated Nutrition (Rounded): {final_rounded_result}")
        logger.info(f"Processed Items: {total_nutrition['items_processed']}")
        if total_nutrition['items_failed']:
            logger.warning(f"Failed Items: {total_nutrition['items_failed']}")
        return final_rounded_result # Return the rounded dictionary
    else:
        logger.error("Failed to process nutrition for all items in the list.")
        return None 