from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt

from kavach_saathi.db import Base, SessionLocal, get_engine
from kavach_saathi.db.models import (
    Address,
    AgentLog,
    BuyerTrustSignal,
    CartItem,
    EvalFixture,
    Order,
    OrderItem,
    OrderStatusHistory,
    OtpSession,
    Payment,
    Product,
    ProductImage,
    ProductSpecification,
    ProductVariant,
    RazorpayWebhookEvent,
    RefreshToken,
    ReturnRecord,
    Review,
    SellerProfile,
    SellerTrustScoreRecord,
    SupportInteraction,
    User,
    WishlistItem,
    WorkflowRun,
)
from kavach_saathi.digipin import encode
from kavach_saathi.order_status import OrderStatus

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260713
DEFAULT_PASSWORD = "KavachDemo@2026"

CATEGORY_ORDER = [
    "Popular",
    "Kurti, Saree & Lehenga",
    "Women Western",
    "Lingerie",
    "Men",
    "Kids & Toys",
    "Home & Kitchen",
    "Beauty & Health",
    "Jewellery & Accessories",
    "Bags & Footwear",
]

# Ethnic is generated first so P-001 remains the golden eight-agent demo product.
CATEGORY_SPECS = {
    "Kurti, Saree & Lehenga": {
        "items": [
            "Floral Cotton Kurta",
            "Block Print Kurti",
            "Chikankari Kurta",
            "Anarkali Set",
            "Silk Blend Saree",
            "Bandhani Saree",
            "Embroidered Lehenga",
            "Palazzo Suit Set",
            "Festive Dupatta Set",
            "Straight Office Kurta",
        ],
        "brands": ["Saheli", "Rangrez", "Noor", "Aarohi", "Satrangi"],
        "materials": ["Cotton Viscose", "Rayon", "Chanderi Blend", "Art Silk", "Cotton Slub"],
        "occasions": ["Everyday", "Office", "Festive", "Wedding guest", "Family gathering"],
        "audience": "Women",
        "price": (349, 1599),
        "narrative": "high-intent ethnic fashion with label-backed fabric and fit evidence",
        "sized": True,
    },
    "Women Western": {
        "items": [
            "Wrap Midi Dress",
            "Relaxed Co-ord Set",
            "High-Rise Wide Leg Jeans",
            "Ribbed Crop Top",
            "Oversized Cotton Shirt",
            "Pleated A-Line Skirt",
            "Tailored Work Trousers",
            "Printed Jumpsuit",
            "Denim Jacket",
            "Everyday Maxi Dress",
        ],
        "brands": ["Urban Muse", "Mysa", "Novi", "Street Bloom", "Twenty Nine"],
        "materials": ["Cotton Blend", "Viscose", "Denim", "Poly Crepe", "Rib Knit"],
        "occasions": ["College", "Office", "Brunch", "Travel", "Evening"],
        "audience": "Women",
        "price": (299, 1799),
        "narrative": "trend-led western wear balanced with practical fit guidance",
        "sized": True,
    },
    "Lingerie": {
        "items": [
            "Seamless Everyday Bra",
            "Cotton T-Shirt Bra",
            "Wirefree Lounge Bra",
            "High-Waist Brief Set",
            "Cotton Hipster Pack",
            "Satin Night Suit",
            "Printed Pyjama Set",
            "Shaping Camisole",
            "Maternity Feeding Bra",
            "Soft Robe Set",
        ],
        "brands": ["Nivara", "Softly", "Inner Ease", "Aara", "Comfort Edit"],
        "materials": ["Cotton Elastane", "Microfibre", "Modal Blend", "Satin", "Rib Cotton"],
        "occasions": ["Everyday", "Sleepwear", "Maternity", "Lounge", "Travel"],
        "audience": "Women",
        "price": (199, 999),
        "narrative": "comfort-first essentials with transparent fabric and care details",
        "sized": True,
    },
    "Men": {
        "items": [
            "Oxford Casual Shirt",
            "Slim Fit Formal Shirt",
            "Polo T-Shirt",
            "Cargo Joggers",
            "Straight Fit Jeans",
            "Cotton Kurta",
            "Track Pant Set",
            "Lightweight Bomber Jacket",
            "Performance Sports Tee",
            "Chino Trousers",
        ],
        "brands": ["Northfield", "Udaan Men", "High Street", "Workday", "Sprint"],
        "materials": ["Cotton", "Cotton Lycra", "Denim", "Polyester Knit", "Linen Blend"],
        "occasions": ["Everyday", "Office", "Festive", "Workout", "Travel"],
        "audience": "Men",
        "price": (299, 1899),
        "narrative": "versatile menswear with consistent cross-seller size translation",
        "sized": True,
    },
    "Kids & Toys": {
        "items": [
            "Girls Party Frock",
            "Boys Kurta Set",
            "Cotton Romper Pack",
            "Kids Night Suit",
            "Printed T-Shirt Set",
            "STEM Building Blocks",
            "Wooden Shape Sorter",
            "Musical Activity Toy",
            "Pretend Kitchen Set",
            "Art and Craft Kit",
        ],
        "brands": ["Little Mela", "Playwise", "Mini Udaan", "Tiny Tales", "Happy Hands"],
        "materials": ["Soft Cotton", "Cotton Blend", "BPA-Free Plastic", "Wood", "Paper and Foam"],
        "occasions": ["Everyday", "Birthday", "Learning", "Festive", "Indoor play"],
        "audience": "Kids",
        "price": (199, 1299),
        "narrative": "family-value products combining comfort, safety and learning",
        "sized": True,
    },
    "Home & Kitchen": {
        "items": [
            "Floral Bedsheet Set",
            "Stainless Steel Cookware Set",
            "Airtight Storage Jar Set",
            "Absorbent Bath Towel Set",
            "Cotton Cushion Cover Pack",
            "Non-Stick Fry Pan",
            "Insulated Water Bottle",
            "Kitchen Organizer Rack",
            "LED Table Lamp",
            "Microfibre Door Mat Set",
        ],
        "brands": ["Ghar Saathi", "Rasoi Pro", "Nestora", "Home Bloom", "Daily Living"],
        "materials": ["Cotton", "Stainless Steel", "Borosilicate Glass", "Microfibre", "Food-Grade Plastic"],
        "occasions": ["Daily use", "Housewarming", "Kitchen upgrade", "Home refresh", "Gifting"],
        "audience": "All",
        "price": (199, 2499),
        "narrative": "high-utility home upgrades built around durability and value",
        "sized": False,
    },
    "Beauty & Health": {
        "items": [
            "Aloe Hydration Gel",
            "Vitamin C Face Serum",
            "Gentle Foaming Face Wash",
            "Matte Lip Colour Set",
            "Herbal Hair Oil",
            "Sunscreen SPF 50",
            "Makeup Brush Kit",
            "Digital Weighing Scale",
            "Electric Heating Pad",
            "Wellness Massage Roller",
        ],
        "brands": ["Pure Ritual", "Glowkind", "Ayu Care", "Velvet Hue", "Wellbeing Co"],
        "materials": ["Aloe Formula", "Vitamin Blend", "Herbal Oil", "Cosmetic Grade Fibre", "ABS and Steel"],
        "occasions": ["Daily routine", "Self care", "Travel", "Gifting", "Wellness"],
        "audience": "All",
        "price": (149, 1499),
        "narrative": "accessible self-care with clear usage and package-label claims",
        "sized": False,
    },
    "Jewellery & Accessories": {
        "items": [
            "Pearl Drop Earrings",
            "Oxidised Jhumka Set",
            "Layered Pendant Necklace",
            "Kundan Choker Set",
            "Minimal Bracelet Stack",
            "Classic Analog Watch",
            "Printed Hair Scrunchie Pack",
            "Crystal Hair Clip Set",
            "UV Protection Sunglasses",
            "Silk Feel Scarf",
        ],
        "brands": ["Zariya", "Nazaakat", "Adore", "Gleam", "Studio Accessory"],
        "materials": ["Alloy", "Brass", "Faux Pearl", "Stainless Steel", "Poly Silk"],
        "occasions": ["Everyday", "Festive", "Wedding guest", "Office", "Gifting"],
        "audience": "Women",
        "price": (129, 1299),
        "narrative": "high-visual accessories with clear material disclosure",
        "sized": False,
    },
    "Bags & Footwear": {
        "items": [
            "Structured Tote Bag",
            "Quilted Sling Bag",
            "Everyday Backpack",
            "Travel Duffle Bag",
            "Laptop Messenger Bag",
            "Women Cushioned Sneakers",
            "Men Running Shoes",
            "Embroidered Juttis",
            "Comfort Slide Sandals",
            "Block Heel Sandals",
        ],
        "brands": ["Carry All", "Roadmate", "Stepwise", "Mochi Lane", "Voyager"],
        "materials": ["Vegan Leather", "Canvas", "Polyester", "Mesh and EVA", "Textile"],
        "occasions": ["Everyday", "Commute", "Travel", "Festive", "Workout"],
        "audience": "All",
        "price": (249, 2199),
        "narrative": "fashion-meets-function products with practical use-case proof",
        "sized": False,
    },
    "Popular": {
        "items": [
            "Viral Floral Kurta Set",
            "Bestseller Everyday Saree",
            "Trending Oversized Shirt",
            "Customer-Favourite Co-ord",
            "Top-Rated Storage Set",
            "Most-Loved Sling Bag",
            "Trending Cushion Sneakers",
            "Viral Kundan Jewellery Set",
            "Bestseller Skin Care Duo",
            "Top-Pick Kids Activity Kit",
        ],
        "brands": ["Meesho Picks", "Value Star", "Loved by India", "Trend Edit", "Smart Buy"],
        "materials": ["Cotton Blend", "Art Silk", "Vegan Leather", "Mixed Media", "Label Verified"],
        "occasions": ["Everyday", "Trending now", "Gifting", "Festive", "Smart value"],
        "audience": "All",
        "price": (249, 1799),
        "narrative": "cross-category hero products selected for strong value and social proof",
        "sized": False,
    },
}

COLORS = [
    ("Berry", "#8A3156"),
    ("Indigo", "#4657A7"),
    ("Saffron", "#D58A20"),
    ("Emerald", "#178060"),
    ("Rose", "#D45475"),
]


def size_chart(offset: int = 0) -> dict[str, dict[str, int]]:
    return {
        "XS": {"chest": 86 + offset, "waist": 80 + offset, "length": 110},
        "S": {"chest": 91 + offset, "waist": 85 + offset, "length": 111},
        "M": {"chest": 97 + offset, "waist": 91 + offset, "length": 112},
        "L": {"chest": 102 + offset, "waist": 97 + offset, "length": 113},
        "XL": {"chest": 109 + offset, "waist": 104 + offset, "length": 114},
        "XXL": {"chest": 117 + offset, "waist": 112 + offset, "length": 115},
    }


def make_sellers() -> list[dict]:
    cities = ["Surat", "Jaipur", "Lucknow", "Delhi", "Ahmedabad", "Kolkata"]
    names = [
        "Surat Saheli Studio",
        "Jaipur Rangrez",
        "Lucknow Chikan Works",
        "Narmada Ethnic",
        "Gulabi Looms",
        "Saanjh Apparel",
        "Udaan Fashion House",
        "Noor Textiles",
        "Pragati Collections",
        "Aarohi Trends",
        "Satrangi Bazaar",
        "Nayi Disha Living",
    ]
    return [
        {
            "id": f"S-{index:03d}",
            "name": name,
            "city": cities[(index - 1) % len(cities)],
            "rating": round(3.8 + (index % 6) * 0.18, 2),
            "on_time_rate": 86 + index % 12,
            "return_rate": 8 + index % 9,
            "verified": index not in {8, 11},
        }
        for index, name in enumerate(names, 1)
    ]


def make_products() -> list[dict]:
    rng = random.Random(SEED)
    products: list[dict] = []
    generation_order = [category for category in CATEGORY_SPECS if category != "Popular"] + ["Popular"]
    for category in generation_order:
        config = CATEGORY_SPECS[category]
        for item_index, item in enumerate(config["items"]):
            for variant_index, (color, color_hex) in enumerate(COLORS):
                index = len(products) + 1
                seller_index = ((index - 1) % 12) + 1
                product_materials = config["materials"]
                product_sized = config["sized"]
                if category == "Kids & Toys":
                    if item_index < 5:
                        product_materials = ["Soft Cotton", "Cotton Blend"]
                    else:
                        product_materials = ["BPA-Free Plastic", "Wood", "Paper and Foam"]
                        product_sized = False
                elif category == "Popular":
                    # First 4 items (Kurta Set, Saree, Shirt, Co-ord) are garments and
                    # should get a real size chart; the rest (storage, bags, footwear,
                    # jewellery, skincare, kids kit) are non-garment and stay unsized.
                    product_sized = item_index < 4
                material = product_materials[(item_index + variant_index) % len(product_materials)]
                occasion = config["occasions"][(item_index + variant_index) % len(config["occasions"])]
                brand = config["brands"][(item_index + variant_index) % len(config["brands"])]
                floor, ceiling = config["price"]
                price = floor + ((item_index * 5 + variant_index) * 97) % max(100, ceiling - floor)
                price = int(round(price / 10) * 10 - 1)
                original_price = int(round((price * (1.7 + (variant_index % 3) * 0.18)) / 10) * 10 + 1)
                rating = round(4.0 + ((index * 7) % 9) * 0.1, 1)
                review_count = 180 + rng.randint(40, 18400)
                stock = 8 + (index * 13) % 190
                delivery_days = 2 + index % 5
                name = f"{color} {item}"
                if index == 1:
                    name = "Maroon Floral Cotton Kurta"
                    brand = "Saheli"
                    material = "Cotton Viscose"
                    occasion = "Everyday"
                    price = 349
                    original_price = 799
                    color_hex = "#800000"
                    rating = 4.4
                    review_count = 12840
                    stock = 74
                    delivery_days = 3
                fabric = "60% Cotton, 40% Viscose" if index == 1 else material
                gsm = 150 if index == 1 else (0 if not product_sized else 135 + (index % 8) * 10)
                copied = index in {173, 347}
                products.append(
                    {
                        "id": f"P-{index:03d}",
                        "name": name,
                        "brand": brand,
                        "seller_id": f"S-{seller_index:03d}",
                        "category": category,
                        "audience": config["audience"],
                        "description": (
                            f"Designed for {occasion.lower()}, this {item.lower()} uses {material.lower()} "
                            f"for value-conscious Indian shoppers. Clear specifications, verified media "
                            f"and seller evidence make it ready for an agent-protected purchase."
                        ),
                        "price": price,
                        "original_price": original_price,
                        "rating": rating,
                        "review_count": review_count,
                        "stock": stock,
                        "delivery_days": delivery_days,
                        "free_delivery": True,
                        "cod_available": index % 11 != 0,
                        "occasion": occasion,
                        "material": material,
                        "highlights": [
                            f"{material} construction with label-backed care guidance",
                            f"Ships in {delivery_days}–{delivery_days + 2} days with free delivery",
                            f"{review_count:,} shopper ratings represented in the demo catalogue",
                        ],
                        "badges": ["Agent verified", "Free delivery", "7-day returns"],
                        "presentation": {
                            "hook": f"One of 50 presentation-ready products in {category}.",
                            "why_it_wins": (
                                f"Demonstrates {config['narrative']} at a strong ₹{price} price point."
                            ),
                            "proof_points": [
                                f"{rating}/5 catalogue rating",
                                f"{stock} units in mock inventory",
                                f"Verified seller S-{seller_index:03d}",
                            ],
                        },
                        "specs": {
                            "fabric": fabric,
                            "gsm": gsm,
                            "color_hex": color_hex,
                            "wash_care": "Gentle hand wash" if product_sized else "Follow package label",
                        },
                        "label_backed_fields": ["fabric", "gsm", "color_hex", "wash_care"],
                        "size_chart": (
                            size_chart(
                                offset=(
                                    -6
                                    if index == 1
                                    else (-3 if index % 3 == 0 else (2 if index % 4 == 0 else 0))
                                )
                            )
                            if product_sized
                            else {}
                        ),
                        "return_window_days": 7,
                        "media": {
                            "primary": f"assets/mock/products/P-{index:03d}.png",
                            "care_label": f"assets/mock/labels/P-{index:03d}-care.png",
                        },
                        "ground_truth": {
                            "catalogue": {
                                "quality": round(0.76 + (index % 6) * 0.035, 2),
                                "full_matches": ["https://example.test/copied-stock-photo"] if copied else [],
                                "partial_matches": [],
                                "pages": ["https://example.test/source-page"] if copied else [],
                            }
                        },
                    }
                )
    return products


def make_buyers() -> list[dict]:
    first_names = ["Sunita", "Asha", "Rekha", "Pooja", "Farida", "Meena", "Kavita", "Lata", "Rani", "Neha"]
    cities = ["Bilaspur", "Patna", "Jaipur", "Lucknow", "Indore"]
    languages = ["hi", "hi", "hi", "en", "hi", "bn", "mr", "hi", "gu", "en"]
    return [
        {
            "id": f"B-{index:03d}",
            "name": name,
            "city": cities[(index - 1) % len(cities)],
            "language": languages[index - 1],
            "measurements_cm": {
                "chest": 92 + ((index - 1) % 4) * 4,
                "waist": 84 + ((index - 1) % 4) * 4,
                "height": 154 + index * 2,
            },
            "trusted_returner": index in {1, 2, 4, 7},
        }
        for index, name in enumerate(first_names, 1)
    ]


def make_orders(products: list[dict]) -> list[dict]:
    orders: list[dict] = []
    statuses = ["delivered", "delivered", "shipped", "cancelled", "delivered"]
    for index in range(1, 201):
        buyer_index = ((index - 1) % 10) + 1
        product_index = ((index * 7 - 1) % len(products)) + 1
        product = products[product_index - 1]
        orders.append(
            {
                "id": f"O-{index:03d}",
                "buyer_id": f"B-{buyer_index:03d}",
                "product_id": product["id"],
                "seller_id": product["seller_id"],
                "status": statuses[index % len(statuses)],
                "size": ["S", "M", "L", "XL", "XXL"][index % 5],
                "fit_feedback": "good" if index % 4 else "tight",
                "return_outcome": "approved" if index % 9 == 0 else None,
                "order_value": product["price"],
            }
        )
    orders[0].update(
        {
            "id": "O-GOLDEN",
            "buyer_id": "B-001",
            "product_id": "P-001",
            "seller_id": "S-001",
            "status": "delivered",
            "size": "XL",
            "fit_feedback": "good",
            "return_outcome": None,
            "order_value": 349,
        }
    )
    orders[1].update(
        {
            "buyer_id": "B-001",
            "product_id": "P-011",
            "seller_id": products[10]["seller_id"],
            "size": "L",
            "fit_feedback": "good",
        }
    )
    return orders


# Weighted so the mix looks like a real marketplace (mostly happy buyers, a genuine
# tail of complaints) rather than a flat/uniform spread across 1-5.
_RATING_POOL = [5] * 42 + [4] * 28 + [3] * 16 + [2] * 8 + [1] * 6

_REVIEW_TEMPLATES = {
    5: [
        "Bahut accha product hai, {material} ki quality expected se bhi better nikli!",
        "Perfect fit aur finishing, bilkul jaisa photo mein dikhaya tha waisa hi mila.",
        "Paisa vasool! {category} mein itni acchi quality kam price mein milna mushkil hai.",
        "Delivery bhi time pe aa gayi aur product bhi top notch hai, highly recommended.",
        "Family ke liye leke aayi thi, sabko bahut pasand aaya. 5 star deserve karta hai.",
        "Second time order kiya hai isi seller se, quality consistent hai.",
        "Excellent quality for the price, {material} feels premium and durable.",
        "Bilkul original jaisa hai, koi complaint nahi. Will order again.",
        "Great value for money, packaging bhi bahut acchi thi.",
        "Superb! Colour bhi exactly wahi hai jo photo mein tha.",
        "Best purchase this month, quality aur comfort dono ekdum sahi.",
        "As described, no defects, fits perfectly. Very happy with this purchase.",
        "Loved it! {material} ka feel bahut soft aur comfortable hai.",
        "Genuinely impressed, itni detail ke saath banaya gaya hai product.",
        "5 stars for sure, exceeded my expectations completely.",
    ],
    4: [
        "Accha product hai, bas delivery thodi late ho gayi thi.",
        "Quality achi hai lekin size thoda tight nikla, exchange karna pada.",
        "Overall satisfied, {material} ki feel achi hai bas color thoda alag laga screen se.",
        "Good product for the price, packaging aur better ho sakti thi.",
        "Nice quality, ek do jagah stitching thodi loose thi but overall theek hai.",
        "Value for money hai, thoda aur variety hoti to accha hota.",
        "Comfortable and good looking, size chart thoda confusing tha.",
        "Product achha hai, bas customer service thodi slow respond karti hai.",
        "Satisfied with the purchase, expected slightly better finishing though.",
        "Decent quality, {category} ke hisaab se price bhi reasonable hai.",
        "Good but not great, kuch cheezein improve ho sakti hain.",
        "Works well, thoda smell aa raha tha initially but wash karne ke baad theek ho gaya.",
        "Nice fabric feel, color thoda halka hai photo ke comparison mein.",
        "Happy with the purchase overall, delivery could've been faster.",
        "Pretty good for daily use, bas ek button loose tha jo maine khud sahi kar liya.",
    ],
    3: [
        "Average product hai, jo expect kiya tha utna nahi mila.",
        "Thik thak hai, na acha na bura, average quality.",
        "{material} quality theek hai but price ke hisaab se kuch aur expect kiya tha.",
        "Product usable hai lekin finishing mein kami hai.",
        "Size thoda mismatch tha, quality average lagi.",
        "Delivery time pe hui, product bas theek thaak hai.",
        "Kaam chal jaayega, but repurchase nahi karungi.",
        "Mixed feelings, kuch acha kuch improve karne layak hai.",
        "Okayish product, photo se thoda alag nikla.",
        "Not bad, not great, does the job for now.",
        "Quality average hai, is price range mein better options bhi honge.",
        "Product theek hai but packaging damaged aayi thi.",
        "Satisfactory but nothing special about this one.",
        "Would've expected better {material} quality at this price point.",
        "Decent for occasional use, daily use ke liye durable nahi lagta.",
    ],
    2: [
        "Quality expected se kam nikli, thoda disappoint hui.",
        "Product photo jaisa nahi laga, {material} bhi cheap feel ho raha hai.",
        "Size sahi nahi tha aur return process bhi lengthy hai.",
        "Stitching kharab thi, ek hi wash mein loose ho gayi.",
        "Not worth the price, better options available elsewhere.",
        "Delivery late hui aur product bhi damaged mila.",
        "Disappointed with the quality, expected better from the description.",
        "Color bilkul alag tha jo dikhaya gaya tha usse.",
        "Fitting issue tha, exchange karna pada jo hassle raha.",
        "Cheap material use kiya gaya hai, price ke hisaab se theek nahi laga.",
        "Product mein defect tha, customer care se contact karna pada.",
        "Expected better packaging, product thoda damaged condition mein aaya.",
        "Not satisfied, quality control better honi chahiye.",
        "{category} ke hisaab se yeh product average se bhi kam hai.",
        "Won't recommend, quality issues within first use.",
    ],
    1: [
        "Bahut bekaar product hai, paisa waste ho gaya.",
        "Product turant kharab ho gaya, ek din bhi nahi chala.",
        "Total waste of money, quality bilkul bhi acchi nahi hai.",
        "Fake material lagta hai, bilkul bhi original jaisa nahi.",
        "Delivery mein bahut delay hua aur product bhi defective mila.",
        "Worst purchase ever, seller se refund maang rahi hoon.",
        "Product photo se bilkul match nahi karta, misleading listing hai.",
        "Itni ghatiya quality expect nahi ki thi, bahut nirasha hui.",
        "Size completely wrong tha aur return bhi nahi ho raha.",
        "{material} bilkul cheap feel hota hai, ek hi din mein phat gaya.",
        "Customer service ne bhi koi help nahi ki, very disappointed.",
        "Do not buy, quality is extremely poor for this price.",
        "Product damaged aaya aur seller ne exchange se mana kar diya.",
        "Complete waste, packaging bhi bahut kharab thi.",
        "Never ordering from this seller again, terrible experience.",
    ],
}

_IRRELEVANT_REASONS = [
    "photo shows a pet instead of the product",
    "photo is a listing screenshot",
    "photo shows unrelated packaging",
]


def make_reviews(products: list[dict]) -> tuple[list[dict], list[dict]]:
    """Random-but-deterministic review count per product (5-10) so bestsellers look
    busy and niche items look thin, like a real marketplace -- rather than every
    product having an identical, obviously-synthetic review count. ~28% of reviews
    carry a photo, and roughly one in eight of those is deliberately a mismatched
    photo (copied from an unrelated product), giving Agent 4's real CLIP+BERT pass
    (see classify_seeded_reviews.py) genuine mismatches to catch instead of every
    photo trivially matching.

    The count is capped at 10 (not the wider range this used to have) because there
    are only 10 seeded buyers total and a `(buyer_id, product_id)` unique constraint
    on the reviews table (one review per buyer per product, same as a real
    marketplace) -- picking a buyer independently per review, rather than sampling
    without replacement from the 10 available, let the same buyer get assigned to the
    same product more than once whenever a product's review count exceeded 10,
    violating that constraint on every single fresh seed (deterministically, not a
    flaky occasional collision, since this is seeded with a fixed RNG).

    Returns (reviews, review_orders): `reviews.order_id` FKs into `orders.id` (a
    "verified purchase" link added after this function was first written), and
    since the 200 orders `make_orders()` generates are an independent random sample
    unrelated to which (buyer, product) pairs get reviewed, there's no guarantee any
    of them actually cover a given review -- every review gets its own dedicated,
    already-delivered order here instead, inserted through the exact same
    Order/OrderItem/OrderStatusHistory/Payment pipeline as `orders` (see
    `seed_database()`).
    """
    rng = random.Random(SEED)
    records: list[dict] = []
    review_orders: list[dict] = []
    for product in products:
        review_count = rng.randint(5, 10)
        buyer_ids = rng.sample(range(1, 11), review_count)
        for buyer_index in buyer_ids:
            index = len(records) + 1
            rating = rng.choice(_RATING_POOL)
            text = rng.choice(_REVIEW_TEMPLATES[rating]).format(
                material=product["material"].lower(), category=product["category"].lower()
            )
            has_media = rng.random() < 0.28
            relevant = True if not has_media else rng.random() > 0.12
            created_at = datetime.now(UTC) - timedelta(days=rng.randint(1, 540), hours=rng.randint(0, 23))
            buyer_id = f"B-{buyer_index:03d}"
            order_id = f"O-RV-{index:05d}"
            review_orders.append(
                {
                    "id": order_id,
                    "buyer_id": buyer_id,
                    "product_id": product["id"],
                    "seller_id": product["seller_id"],
                    "status": "delivered",
                    "size": "Standard",
                    "fit_feedback": "good",
                    "return_outcome": None,
                    "order_value": product["price"],
                }
            )
            records.append(
                {
                    "id": f"RV-{index:05d}",
                    "order_id": order_id,
                    "buyer_id": buyer_id,
                    "product_id": product["id"],
                    "rating": rating,
                    "text": text,
                    "media": f"assets/mock/reviews/RV-{index:05d}.png" if has_media else None,
                    "created_at": created_at,
                    "expected_relevant": relevant,
                    "similarity_score": (
                        round(0.83 + (index % 9) * 0.012, 2)
                        if relevant
                        else round(0.08 + (index % 7) * 0.02, 2)
                    ),
                    "relevance_reason": (
                        "review media matches product color and silhouette"
                        if relevant
                        else _IRRELEVANT_REASONS[index % len(_IRRELEVANT_REASONS)]
                    ),
                }
            )

    # tests/test_api_workflows.py and scripts/evaluate_demo.py's golden path both
    # exercise a fixed RV-GOOD/RV-BAD pair on P-001 -- keep those two literal IDs and
    # image paths stable regardless of the randomized generation above. `.update()`
    # only overwrites the given keys, so each record keeps the order_id already
    # assigned to it above.
    p001_indices = [i for i, record in enumerate(records) if record["product_id"] == "P-001"]
    records[p001_indices[0]].update(
        {
            "id": "RV-GOOD",
            "media": "assets/mock/reviews/RV-GOOD.png",
            "expected_relevant": True,
            "similarity_score": 0.94,
            "relevance_reason": "review media matches product color and silhouette",
        }
    )
    records[p001_indices[1]].update(
        {
            "id": "RV-BAD",
            "media": "assets/mock/reviews/RV-BAD.png",
            "expected_relevant": False,
            "similarity_score": 0.09,
            "relevance_reason": "photo shows unrelated packaging",
        }
    )
    return records, review_orders


def make_addresses() -> list[dict]:
    examples = [
        ("Hanuman Mandir ke peeche, gali no. 3", "Bilaspur", "Chhattisgarh", "495001", 22.0797, 82.1409),
        ("Panchayat bhawan ke saamne", "Patna", "Bihar", "800001", 25.5941, 85.1376),
        ("Purani masjid wali gali", "Jaipur", "Rajasthan", "302001", 26.9124, 75.7873),
        ("Water tank ke paas", "Lucknow", "Uttar Pradesh", "226001", 26.8467, 80.9462),
    ]
    records = []
    for index in range(40):
        raw, city, state, pin, lat, lon = examples[index % len(examples)]
        lat += (index // 4) * 0.0003
        lon += (index // 4) * 0.0003
        records.append(
            {
                "id": f"A-{index + 1:03d}",
                "buyer_id": f"B-{(index % 10) + 1:03d}",
                "raw_address": raw,
                "city": city,
                "state": state,
                "postal_pin": pin if index % 5 else "110001",
                "expected_postal_pin": pin,
                "coordinates": {"latitude": lat, "longitude": lon},
                "digipin": encode(lat, lon),
                "expected_valid": index % 5 != 0,
            }
        )
    return records


def make_returns(orders: list[dict]) -> list[dict]:
    cases = []
    for index, order in enumerate(orders[:60], 1):
        group = index % 3
        if group == 1:
            evidence = {
                "tag_visible": True,
                "label_matches": True,
                "product_matches": True,
                "packaging_matches": True,
            }
            confidence = 96
            expected = "approve"
        elif group == 2:
            evidence = {
                "tag_visible": False,
                "label_matches": True,
                "product_matches": True,
                "packaging_matches": True,
            }
            confidence = 68
            expected = "request_more_evidence"
        else:
            evidence = {
                "tag_visible": False,
                "label_matches": False,
                "product_matches": False,
                "packaging_matches": True,
            }
            confidence = 24
            expected = "manual_inspection"
        cases.append(
            {
                "id": f"RT-{index:03d}",
                "order_id": order["id"],
                "video": f"assets/mock/returns/return-{expected}.mp4",
                "evidence": evidence,
                "expected_confidence": confidence,
                "expected_decision": expected,
            }
        )
    cases[0].update(
        {
            "id": "RT-GOLDEN",
            "order_id": "O-GOLDEN",
            "expected_confidence": 96,
            "expected_decision": "approve",
        }
    )
    return cases


ORDER_STATUS_MAP = {
    "delivered": OrderStatus.DELIVERED,
    "shipped": OrderStatus.SHIPPED,
    "cancelled": OrderStatus.CANCELLED,
}


def _hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def reset_database() -> None:
    """Delete all rows (children first) without dropping the Alembic-managed schema."""
    with SessionLocal() as session:
        for model in (
            EvalFixture,
            AgentLog,
            CartItem,
            WishlistItem,
            OrderStatusHistory,
            RazorpayWebhookEvent,
            Payment,
            OrderItem,
            ReturnRecord,
            Review,
            ProductImage,
            ProductSpecification,
            ProductVariant,
            SupportInteraction,
            WorkflowRun,
            Order,
            OtpSession,
            Address,
            Product,
            BuyerTrustSignal,
            SellerTrustScoreRecord,
            RefreshToken,
            SellerProfile,
            User,
        ):
            session.query(model).delete()
        session.commit()


def _export_reviews_json(reviews: list[dict]) -> None:
    """Keeps data/seed/reviews.json in sync with make_reviews()'s live output --
    scripts/generate_fixture_media.py (review photo generation) and
    scripts/evaluate_demo.py (accuracy scoring against expected_relevant) both read
    this file directly rather than the Postgres DB, so a stale copy would silently
    make those scripts test against a different review set than what's actually
    seeded."""
    export = [{**review, "created_at": review["created_at"].isoformat()} for review in reviews]
    (ROOT / "data" / "seed" / "reviews.json").write_text(
        json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def seed_database() -> dict[str, int]:
    sellers = make_sellers()
    products = make_products()
    buyers = make_buyers()
    orders = make_orders(products)
    reviews, review_orders = make_reviews(products)
    _export_reviews_json(reviews)
    addresses = make_addresses()
    returns = make_returns(orders)
    password_hash = _hash_password(DEFAULT_PASSWORD)

    with SessionLocal() as session:
        # Admin account for the admin console (Sub-phase 10).
        session.add(
            User(
                id="ADMIN-001",
                role="admin",
                name="Kavach Saathi Admin",
                email="admin@kavachsaathi.test",
                password_hash=password_hash,
                preferred_language="en",
            )
        )

        # Pass 1: all User rows first. SQLAlchemy's flush ordering only follows declared
        # relationship() dependency graphs, not bare ForeignKey columns, so child rows
        # (seller/buyer profiles) must be added in a separate pass after this flush.
        for seller in sellers:
            session.add(
                User(
                    id=seller["id"],
                    role="seller",
                    name=seller["name"],
                    email=f"{seller['id'].lower()}@seller.kavachsaathi.test",
                    password_hash=password_hash,
                    preferred_language="en",
                    city=seller["city"],
                )
            )
        for buyer in buyers:
            session.add(
                User(
                    id=buyer["id"],
                    role="buyer",
                    name=buyer["name"],
                    email=f"{buyer['id'].lower()}@buyer.kavachsaathi.test",
                    password_hash=password_hash,
                    preferred_language=buyer["language"],
                    city=buyer["city"],
                    measurements_cm=buyer["measurements_cm"],
                    trusted_returner=buyer["trusted_returner"],
                )
            )
        session.flush()

        # Pass 2: rows that reference the users just flushed.
        for seller in sellers:
            session.add(
                SellerProfile(
                    user_id=seller["id"],
                    business_name=seller["name"],
                    digilocker_kyc_status="verified",
                    trust_score=round(seller["rating"] * 20, 1),
                    city=seller["city"],
                    rating=seller["rating"],
                    on_time_rate=seller["on_time_rate"],
                    return_rate=seller["return_rate"],
                    verified=seller["verified"],
                )
            )
            session.add(
                SellerTrustScoreRecord(
                    seller_id=seller["id"],
                    catalog_accuracy_score=round(90 - seller["return_rate"] * 0.8, 1),
                    rto_rate=float(seller["return_rate"]),
                    fraud_flags=0,
                )
            )
        for buyer in buyers:
            session.add(
                BuyerTrustSignal(
                    buyer_id=buyer["id"],
                    return_rate=0.1 if buyer["trusted_returner"] else 0.22,
                    fraud_flags=0,
                    trusted_returner_badge_bool=buyer["trusted_returner"],
                )
            )
        session.flush()

        for product in products:
            copied = bool(product["ground_truth"]["catalogue"]["full_matches"])
            session.add(
                Product(
                    id=product["id"],
                    seller_id=product["seller_id"],
                    title=product["name"],
                    brand=product["brand"],
                    description=product["description"],
                    category=product["category"],
                    audience=product["audience"],
                    occasion=product["occasion"],
                    material=product["material"],
                    price=product["price"],
                    original_price=product["original_price"],
                    status="active",
                    spec_json=product["specs"],
                    label_backed_fields=product["label_backed_fields"],
                    spec_source="seller_form",
                    stolen_photo_flag=copied,
                    rating=product["rating"],
                    review_count=product["review_count"],
                    stock=product["stock"],
                    delivery_days=product["delivery_days"],
                    free_delivery=product["free_delivery"],
                    cod_available=product["cod_available"],
                    return_window_days=product["return_window_days"],
                    highlights=product["highlights"],
                    badges=product["badges"],
                    presentation=product["presentation"],
                    size_chart=product["size_chart"],
                    media_primary=product["media"]["primary"],
                    media_care_label=product["media"]["care_label"],
                )
            )
        session.flush()

        for product in products:
            for key, value in product["specs"].items():
                session.add(ProductSpecification(
                    product_id=product["id"], key=key, label=key.replace("_", " ").title(),
                    value_json=value, value_type="number" if isinstance(value, (int, float)) else "text",
                    unit="GSM" if key == "gsm" else ("cm" if key.endswith("_cm") else None),
                    comparison_group=(
                        "fabric" if key in {"fabric", "gsm"} else ("color" if "color" in key else "general")
                    ),
                    comparable=True, source="seller_form", verified=key in product["label_backed_fields"],
                ))
            session.add(
                EvalFixture(
                    entity_type="product",
                    entity_id=product["id"],
                    payload=product["ground_truth"],
                )
            )
            session.add(
                ProductImage(
                    id=f"{product['id']}-seller-front",
                    product_id=product["id"],
                    url=product["media"]["primary"],
                    type="seller_upload",
                    angle="front",
                    is_verified=False,
                )
            )
            for angle in ("front", "back", "left", "right"):
                session.add(
                    ProductImage(
                        id=f"{product['id']}-{angle}",
                        product_id=product["id"],
                        url=f"assets/mock/catalog/{product['id']}-{angle}.png",
                        type="ai_generated",
                        angle=angle,
                        is_verified=False,
                    )
                )
            chart = product["size_chart"]
            if chart:
                per_size_stock = max(1, product["stock"] // max(1, len(chart)))
                for size in chart:
                    session.add(
                        ProductVariant(
                            id=f"{product['id']}-{size}",
                            product_id=product["id"],
                            size=size,
                            sku=f"{product['id']}-{size}",
                            stock_qty=per_size_stock,
                            price=product["price"],
                        )
                    )
            else:
                session.add(
                    ProductVariant(
                        id=f"{product['id']}-STD",
                        product_id=product["id"],
                        size="Standard",
                        sku=f"{product['id']}-STD",
                        stock_qty=product["stock"],
                        price=product["price"],
                    )
                )
        session.flush()

        order_statuses: dict[str, OrderStatus] = {}
        order_variants: dict[str, str | None] = {}
        for order in orders + review_orders:
            status = ORDER_STATUS_MAP.get(order["status"], OrderStatus.PLACED)
            variant_id = f"{order['product_id']}-{order['size']}"
            if session.get(ProductVariant, variant_id) is None:
                variant_id = f"{order['product_id']}-STD"
                if session.get(ProductVariant, variant_id) is None:
                    variant_id = None
            order_statuses[order["id"]] = status
            order_variants[order["id"]] = variant_id
            session.add(
                Order(
                    id=order["id"],
                    buyer_id=order["buyer_id"],
                    status=status,
                    total_amount=order["order_value"],
                    payment_mode="cod",
                    fit_feedback=order["fit_feedback"],
                    return_outcome=order["return_outcome"],
                )
            )
        session.flush()

        for order in orders + review_orders:
            status = order_statuses[order["id"]]
            session.add(
                OrderItem(
                    order_id=order["id"],
                    product_id=order["product_id"],
                    product_variant_id=order_variants[order["id"]],
                    seller_id=order["seller_id"],
                    size=order["size"],
                    qty=1,
                    price_at_purchase=order["order_value"],
                )
            )
            session.add(
                OrderStatusHistory(
                    order_id=order["id"],
                    status=status,
                    actor="system",
                )
            )
            session.add(
                Payment(
                    id=f"PAY-{order['id']}",
                    order_id=order["id"],
                    provider="cod",
                    status="paid" if status == OrderStatus.DELIVERED else "pending",
                    amount=order["order_value"],
                )
            )
        session.flush()

        for review in reviews:
            session.add(
                Review(
                    id=review["id"],
                    product_id=review["product_id"],
                    buyer_id=review["buyer_id"],
                    order_id=review["order_id"],
                    rating=review["rating"],
                    text=review["text"],
                    media=review["media"],
                    is_hidden_by_agent=False,
                    created_at=review["created_at"],
                )
            )
            session.add(
                EvalFixture(
                    entity_type="review",
                    entity_id=review["id"],
                    payload={
                        "expected_relevant": review["expected_relevant"],
                        "similarity_score": review["similarity_score"],
                        "relevance_reason": review["relevance_reason"],
                    },
                )
            )

        for index, address in enumerate(addresses):
            session.add(
                Address(
                    id=address["id"],
                    user_id=address["buyer_id"],
                    raw_text=address["raw_address"],
                    city=address["city"],
                    state=address["state"],
                    postal_pin=address["postal_pin"],
                    digipin=address["digipin"],
                    latitude=address["coordinates"]["latitude"],
                    longitude=address["coordinates"]["longitude"],
                    verified_bool=False,
                    is_default=index < 10,
                )
            )
            session.add(
                EvalFixture(
                    entity_type="address",
                    entity_id=address["id"],
                    payload={
                        "expected_postal_pin": address["expected_postal_pin"],
                        "expected_valid": address["expected_valid"],
                    },
                )
            )

        for ret in returns:
            order = next(o for o in orders if o["id"] == ret["order_id"])
            session.add(
                ReturnRecord(
                    id=ret["id"],
                    order_id=ret["order_id"],
                    product_id=order["product_id"],
                    buyer_id=order["buyer_id"],
                    video_url=ret["video"],
                    confidence_score=None,
                    decision=None,
                )
            )
            session.add(
                EvalFixture(
                    entity_type="return",
                    entity_id=ret["id"],
                    payload={
                        "evidence": ret["evidence"],
                        "expected_confidence": ret["expected_confidence"],
                        "expected_decision": ret["expected_decision"],
                    },
                )
            )

        session.add(
            EvalFixture(
                entity_type="provenance",
                entity_id="dataset-v3",
                payload={
                    "seed": SEED,
                    "strategy": "synthetic category-balanced marketplace fixtures, migrated to Postgres",
                    "contains_real_customer_data": False,
                    "contains_copied_reviews": False,
                    "category_order": CATEGORY_ORDER,
                    "products_per_category": 50,
                    "digipin_reference": "https://github.com/INDIAPOST-gov/digipin",
                    "seed_generated_at": datetime.now(UTC).isoformat(),
                    "default_password": DEFAULT_PASSWORD,
                },
            )
        )

        session.commit()

    return {
        "users": len(sellers) + len(buyers) + 1,
        "products": len(products),
        "orders": len(orders),
        "reviews": len(reviews),
        "addresses": len(addresses),
        "returns": len(returns),
    }


def main() -> None:
    Base.metadata.create_all(bind=get_engine())
    reset_database()
    counts = seed_database()
    print(counts)


if __name__ == "__main__":
    main()
