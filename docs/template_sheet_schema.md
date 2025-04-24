# Calorie Tracker Bot - Google Sheets Schema Documentation

This document provides detailed specifications for setting up and using your Google Sheet with the Calorie Tracker Bot.

## Sheet Structure

### Worksheet Name
The default worksheet name should be "Daily Tracking". If you use a different name, update your bot's configuration accordingly.

### Column Specifications

| Column Name    | Data Type | Format/Units | Required | Description |
|---------------|-----------|--------------|----------|-------------|
| Date          | Date      | YYYY-MM-DD   | Yes      | The tracking date |
| Weight        | Number    | kg/lbs       | No       | Daily weight measurement |
| Weight Time   | Text      | HHMM (24hr)  | No       | Time of weight measurement |
| Sleep Hours   | Number    | Hours        | No       | Hours of sleep (decimals allowed) |
| Sleep Quality | Number    | 1-10         | No       | Subjective sleep quality rating |
| Steps         | Number    | Count        | No       | Daily step count |
| Cardio        | Text      | Description  | No       | Cardio activity description |
| Training      | Text      | Description  | No       | Strength training description |
| Energy Level  | Number    | 1-10         | No       | Subjective energy level rating |
| Mood          | Number    | 1-10         | No       | Subjective mood rating |
| Satiety       | Number    | 1-10         | No       | Subjective fullness/hunger rating |
| Digestion     | Number    | 1-10         | No       | Subjective digestion rating |
| Calories      | Number    | kcal         | Yes      | **Recommended: Use ArrayFormula in header (M1)** See Setup Instructions. |
| Protein       | Number    | grams        | No       | Daily protein intake (Column N) |
| Carbs         | Number    | grams        | No       | Daily carbohydrate intake (Column O) |
| Fat           | Number    | grams        | No       | Daily fat intake (Column P) |
| Fiber         | Number    | grams        | No       | Daily fiber intake |
| Water         | Number    | liters       | No       | Daily water intake |

### Data Type Details

- **Date**: Must be in YYYY-MM-DD format (e.g., 2024-03-20)
- **Numbers**: Use decimal point for fractions (e.g., 7.5)
- **Time**: Use 24-hour format without separators (e.g., 0930 for 9:30 AM)
- **Ratings**: Use whole numbers from 1-10
- **Text**: Free-form text, avoid using commas if possible

## Setup Instructions

1. **Create Your Sheet**:
   - Create a new Google Sheet
   - Import `template_sheet.csv` (File > Import > Upload)
   - Choose "Replace current sheet" when importing
   - Name the worksheet "Daily Tracking"

2. **(Recommended) Add Auto-Calculating Calories Formula:**
   - Click on the header cell for the `Calories` column (likely **M1**).
   - **Important:** Before adding the formula, ensure the cells *below* the header (M2, M3, etc.) are **completely empty**. Delete any existing values or formulas in that column from row 2 downwards.
   - Paste the following formula **exactly** into the formula bar **in cell M1** and press Enter:
     ```
     =ArrayFormula(IF(ROW(A:A)=1, "Calories", IF(AND(A:A<>"", OR(N:N<>"", O:O<>"", P:P<>"")), N:N*4 + O:O*4 + P:P*9, "")))
     ```
   - **Explanation:** This formula keeps "Calories" as the header. For every other row, if **both** the Date (A) column is present **AND** at least one of the Protein (N), Carbs (O), or Fat (P) columns has a value, it calculates `Protein*4 + Carbs*4 + Fat*9` (treating blank macros as 0). Otherwise (if Date is missing OR all macros are blank), it leaves the Calories cell blank.
   - **Troubleshooting:** If you see a `#REF!` error saying "Array result was not expanded because it would overwrite data in M2", it means cell M2 (or another cell below) is not empty. Delete the contents of M2 and any other cells below it in column M.

3. **Share Settings**:
   - Click "Share" in Google Sheets
   - Add your bot's service account email (from your service account JSON file)
   - Grant "Editor" permissions
   - Ensure the sheet is not restricted to specific users/domains if the service account is outside your domain

4. **Get Sheet ID**:
   - Copy the ID from your sheet's URL:
   - Format: `https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit`
   - The ID is the long string between /d/ and /edit

5. **Configure Bot**:
   - Update your bot's configuration with:
     - Sheet ID
     - Worksheet name (if different from "Daily Tracking")
     - Service account credentials

## Data Entry Guidelines

1. **Daily Entries**:
   - Create one row per day
   - Enter data progressively throughout the day
   - Bot will update totals automatically

2. **Missing Data**:
   - Leave cells blank for unknown values
   - Don't use zeros unless that's the actual value
   - Required fields: Date, Calories

3. **Time-based Data**:
   - Enter weight time in 24-hour format
   - Record sleep hours from previous night
   - Update activity logs as they occur

## Troubleshooting

### Common Issues

1. **Access Errors**:
   - Verify service account email is correct
   - Check sharing permissions
   - Ensure sheet is not restricted
   - Confirm worksheet name matches config

2. **Data Format Errors**:
   - Check date format (YYYY-MM-DD)
   - Verify numeric fields contain only numbers
   - Remove any special characters
   - Check for hidden spaces

3. **Update Issues**:
   - Confirm sheet ID is correct
   - Check internet connectivity
   - Verify bot is running
   - Look for error messages in bot logs

### Data Validation

The bot performs these validations:
- Date format and uniqueness
- Numeric field ranges
- Required field presence
- Data type consistency

## Example Data

Here's an example row with realistic data:
```
Date: 2024-03-20
Weight: 85.5
Weight Time: 0930
Sleep Hours: 7.5
Sleep Quality: 8
Steps: 10000
Cardio: 30min run
Training: Legs
Energy Level: 9
Mood: 8
Satiety: 7
Digestion: 8
Calories: 2180
Protein: 150
Carbs: 220
Fat: 80
Fiber: 35
Water: 8
```

## Tips for Success

1. **Consistency**:
   - Update daily, preferably at set times
   - Use consistent formats and units
   - Complete required fields promptly

2. **Accuracy**:
   - Use precise measurements when possible
   - Be honest with subjective ratings
   - Double-check numeric entries

3. **Maintenance**:
   - Regularly verify bot access
   - Back up your sheet periodically
   - Monitor bot notifications

4. **Best Practices**:
   - Keep notes in the reserved column
   - Update progressive totals throughout day
   - Review historical data for trends 