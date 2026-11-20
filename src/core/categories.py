# Fixed category list. The model picks one of MODEL_CATEGORIES; 'settlement' is set by code only.
MODEL_CATEGORIES = {
    "groceries": "supermarket, vegetables, fruit, Costco, Trader Joe's",
    "dining": "restaurants, takeout, coffee, bars",
    "transport": "cabs, Uber, Lyft, transit, gas, parking",
    "rent": "rent, deposits",
    "utilities": "electricity, water, internet, phone bill",
    "household": "cleaning supplies, furniture, repairs",
    "shopping": "clothes, electronics, general purchases",
    "entertainment": "movies, concerts, games, events",
    "travel": "flights, hotels, Airbnb",
    "health": "pharmacy, doctor, gym",
    "subscriptions": "Netflix, Spotify, software",
    "other": "anything else",
}
SETTLEMENT = "settlement"
ALL_CATEGORIES = set(MODEL_CATEGORIES) | {SETTLEMENT}
