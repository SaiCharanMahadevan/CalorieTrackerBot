"""Nutrition Service Package.

Exports the main function to get aggregated nutrition data.
"""

from .api import get_nutrition_for_items

__all__ = ['get_nutrition_for_items'] 