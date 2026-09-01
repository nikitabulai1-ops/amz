"""
Amazon fee reference data for the economics engine.

IMPORTANT — read before trusting these numbers for a real PO decision:
Amazon's official fee schedule lives in Seller Central and changes fee amounts
several times a year (the January 15, 2026 fulfillment fee restructuring and
the ongoing storage/low-inventory-fee changes are examples). During this
build, network egress to sellercentral.amazon.com and to third-party fee
trackers was blocked, so the numbers below are assembled from public 2026
rate-change reporting (see README "Fee data sources") rather than pulled
directly from Amazon's own rate card. Treat every constant here as a
starting estimate, not gospel:

  - Every endpoint that uses these tables accepts fee overrides
    (referral_fee_pct, fulfillment_fee, storage_fee_per_cuft, etc.) so you
    can plug in the exact numbers from Seller Central > Fulfillment by
    Amazon > Fee Schedule, or from the Revenue Calculator, for a specific
    SKU. The defaults only kick in when you don't supply an override.
  - Re-verify these tables at least quarterly, and immediately after any
    Amazon fee-change announcement.
"""

FUEL_AND_LOGISTICS_SURCHARGE_PCT = 0.035

MIN_REFERRAL_FEE = 0.30

# category -> flat rate, or list of (price_ceiling, rate) tuples evaluated
# in order (last tuple should have price_ceiling = None for "and above").
REFERRAL_FEE_TABLE = {
    "default": 0.15,
    "amazon_device_accessories": 0.45,
    "electronics": 0.08,
    "computers": 0.08,
    "major_appliances": 0.08,
    "video_game_consoles": 0.08,
    "automotive_powersports": 0.12,
    "industrial_scientific": 0.12,
    "grocery_gourmet": [(15.00, 0.08), (None, 0.15)],
    "beauty_personal_care": [(10.00, 0.08), (None, 0.15)],
    "furniture": [(200.00, 0.15), (None, 0.10)],
    "jewelry": [(250.00, 0.20), (None, 0.05)],
    "watches": [(1500.00, 0.16), (None, 0.03)],
    "clothing_accessories": [(15.00, 0.05), (20.00, 0.10), (None, 0.17)],
    "baby_products": [(10.00, 0.08), (None, 0.15)],
}

# Approximate 2026 small-standard fulfillment fee by weight band, before the
# 3.5% fuel/logistics surcharge, split by the price bracket Amazon introduced
# 2026-01-15 (items behave differently under/over $10 and $50).
SMALL_STANDARD_FEES = {
    # max_weight_oz: {"under_10": fee, "mid_10_50": fee, "over_50": fee}
    2: {"under_10": 2.88, "mid_10_50": 3.06, "over_50": 3.57},
    4: {"under_10": 3.00, "mid_10_50": 3.19, "over_50": 3.70},
    6: {"under_10": 3.13, "mid_10_50": 3.33, "over_50": 3.84},
    10: {"under_10": 3.33, "mid_10_50": 3.53, "over_50": 4.04},
    16: {"under_10": 3.60, "mid_10_50": 3.81, "over_50": 4.32},
}
LOW_PRICE_FBA_DISCOUNT = 0.86  # applied instead of standard fee for qualifying <$10 low-price enrolled items

LARGE_STANDARD_FEES_BY_WEIGHT_LB = {
    # max_weight_lb: {"mid_10_50": fee, "over_50": fee}  (large standard has no <$10 bracket)
    1: {"mid_10_50": 4.20, "over_50": 4.51},
    2: {"mid_10_50": 4.75, "over_50": 5.06},
    3: {"mid_10_50": 5.42, "over_50": 5.73},
    20: {"mid_10_50": 8.42, "over_50": 8.73},
}

BULKY_FEES_BY_WEIGHT_LB = {
    "small_bulky": {50: 9.61},
    "large_bulky": {50: 19.66},
}

EXTRA_LARGE_FEES_BY_WEIGHT_LB = {
    50: 26.79,
    150: 84.16,
}

OVERMAX_SURCHARGE_RANGE = (17.00, 25.00)  # per unit, on top of Extra-Large fee

STORAGE_FEE_PER_CUFT = {
    "standard": {"jan_sep": 0.78, "q4": 2.40},
    "oversize": {"jan_sep": 0.56, "q4": 1.40},
}

AGED_INVENTORY_SURCHARGE_PER_CUFT_MONTHLY = {
    "180_270_days": 1.50,
    "271_365_days": 3.40,
    "365_plus_days": 6.90,
}

LOW_INVENTORY_LEVEL_FEE_RANGE = (0.32, 2.09)  # per unit sold, applies below days-of-supply threshold
LOW_INVENTORY_DAYS_THRESHOLD = 28  # 35 for some tiers in 2026

HAZMAT_KEYWORDS = [
    "lithium", "battery", "aerosol", "flammable", "magnet", "magnetic",
    "liquid", "powder", "supplement", "essential oil", "alcohol",
    "pressurized", "compressed gas", "corrosive", "oxidizer", "propane",
    "butane", "nail polish", "perfume", "cologne", "bleach", "pesticide",
]

MELTABLE_KEYWORDS = [
    "chocolate", "candy", "gummy", "wax", "candle", "lip balm", "crayon",
    "cosmetic", "lipstick", "suppository",
]

GATED_CATEGORY_KEYWORDS = [
    "grocery", "beauty", "topical", "supplement", "medical device", "otc",
    "jewelry", "fine art", "automotive", "watches", "wine", "alcohol",
    "pesticide", "prescription",
]
