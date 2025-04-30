import unittest
import datetime

# Module to test
from src.services.sheets import utils

class TestSheetsUtils(unittest.TestCase):

    def test_format_date_for_sheet_basic(self):
        """Test standard date formatting."""
        dt = datetime.datetime(2023, 10, 27, 15, 30)
        expected = "Oct 27"
        self.assertEqual(utils.format_date_for_sheet(dt), expected)

    def test_format_date_for_sheet_different_date(self):
        """Test a different date."""
        dt = datetime.datetime(2024, 1, 5, 0, 0) 
        expected = "Jan 05"
        self.assertEqual(utils.format_date_for_sheet(dt), expected)

    def test_format_date_for_sheet_requires_datetime(self):
        """Test that input must be a datetime object."""
        with self.assertRaises(AttributeError):
            # Passing a string instead of datetime should fail
            utils.format_date_for_sheet("2023-10-27") # type: ignore
            
if __name__ == '__main__':
    unittest.main() 