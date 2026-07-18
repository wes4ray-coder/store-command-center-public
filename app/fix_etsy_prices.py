import os
import json
from app.etsy_client import EtsyClient

# Credentials from DB
KEY = "mv8xgy1ds3m7bp0m91gx706w"
SHARED_SECRET = "69lr3mgy2d"
ACCESS_TOKEN = "1260205721.rOLQFM-_V2Zs7JZTNJfDb6y1TR16OySnRbD2y7mGX68lYA3nRCTr3H69GLF3bMY2a8AM6uGkHU3-3_YfogZ-yKLqc"
SHOP_ID = "66778223"

client = EtsyClient(
    keystring=KEY,
    access_token=ACCESS_TOKEN,
    shop_id=SHOP_ID,
    shared_secret=SHARED_SECRET
)

print(f"Fetching active listings for shop {SHOP_ID}...")
try:
    listings = client.get_listings(state="active")
    print(f"Found {len(listings)} active listings.")
    
    updated_count = 0
    for l in listings:
        listing_id = l["listing_id"]
        title = l.get("title", "Unknown")
        price_data = l.get("price", {})
        price_amount = price_data.get("amount", 0)
        
        # Update any listing that is still at $25.00
        if price_amount == 2500:
            print(f"Updating ID {listing_id} ({title[:30]}...) from $25.00 to $15.99")
            res = client.update_listing(
                listing_id=listing_id,
                price={'amount': 1599, 'divisor': 100, 'currency_code': 'USD'}
            )
            print(f"Response: {res}")
            updated_count += 1
            
    print(f"Successfully updated {updated_count} listings.")

except Exception as e:
    print(f"Error: {e}")
