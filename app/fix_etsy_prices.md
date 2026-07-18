# Price Fixer - `fix_etsy_prices.py`

Business logic for calculating and updating prices.

## Purpose
- Receive raw data from Trends and current prices.
- Calculate target prices based on rules.
- Apply discounts/margins.

## Flow
1. Get base price (Printify/Etsy).
2. Apply trend multipliers.
3. Calculate final price.
4. Validate against minimum margins.
