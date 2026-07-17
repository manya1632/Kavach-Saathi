from __future__ import annotations

import re
from pathlib import Path

from kavach_saathi.digipin import decode, encode
from kavach_saathi.repository import CommerceRepository

_SEEDED_PRODUCT_ID = re.compile(r"^P-\d{3}$")


def _seeded_products(repository: CommerceRepository) -> list[dict]:
    """Products from scripts/generate_seed_data.py only, excluding listings real sellers
    create through the seller portal (Sub-phase 2) which now legitimately add rows too."""
    return [product for product in repository.list("products") if _SEEDED_PRODUCT_ID.match(product["id"])]


def test_seed_dataset_counts() -> None:
    # >= rather than == for buyers/sellers/products/orders/reviews/addresses: auth, the
    # seller portal, and real cart/order/review/address-verify endpoints are all real
    # now (Sub-phases 1-2 and 6), so the test suite (and real users) can add rows beyond
    # the seeded baseline over time. returns are the only collection still exclusively
    # seed-script-written (real return creation lands in Sub-phase 9).
    repository = CommerceRepository()
    summary = repository.summary()
    assert summary["products"] >= 500
    assert summary["sellers"] >= 12
    assert summary["buyers"] >= 10
    assert summary["orders"] >= 200
    assert summary["reviews"] >= 1000
    assert summary["addresses"] >= 40
    assert summary["returns"] == 60


def test_catalogue_has_exactly_50_products_in_every_requested_category() -> None:
    products = _seeded_products(CommerceRepository())
    expected_categories = {
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
    }
    counts = {
        category: sum(product["category"] == category for product in products)
        for category in expected_categories
    }
    assert counts == {category: 50 for category in expected_categories}
    assert all(product["description"] and len(product["highlights"]) == 3 for product in products)


def test_kids_apparel_and_toys_use_appropriate_specs() -> None:
    products = _seeded_products(CommerceRepository())
    kids_products = [product for product in products if product["category"] == "Kids & Toys"]
    apparel = kids_products[:25]
    toys = kids_products[25:]
    assert all(product["material"] in {"Soft Cotton", "Cotton Blend"} for product in apparel)
    assert all(product["size_chart"] for product in apparel)
    assert all(product["material"] in {"BPA-Free Plastic", "Wood", "Paper and Foam"} for product in toys)
    assert all(not product["size_chart"] for product in toys)


def test_golden_records_connect() -> None:
    repository = CommerceRepository()
    order = repository.get("orders", "O-GOLDEN")
    assert repository.get("buyers", order["buyer_id"])["name"] == "Sunita"
    assert repository.get("products", order["product_id"])["name"] == "Maroon Floral Cotton Kurta"
    assert repository.return_for_order("O-GOLDEN")["id"] == "RT-GOLDEN"


def test_official_digipin_example() -> None:
    pin = encode(13.11179621, 80.20264269)
    assert pin == "4T396F42L7"
    latitude, longitude = decode(pin)
    assert abs(latitude - 13.11179621) < 0.0001
    assert abs(longitude - 80.20264269) < 0.0001


def test_media_fixture_manifest_exists() -> None:
    manifest = Path("assets/mock/provenance.json")
    assert manifest.exists()
    assert Path("assets/mock/products/P-001.png").exists()
    assert Path("assets/mock/catalog/P-001-front.png").exists()
    assert Path("assets/mock/reviews/RV-BAD.png").exists()
    assert Path("assets/mock/returns/return-approve.mp4").exists()


def test_all_seed_media_references_exist() -> None:
    root = Path(".")
    repository = CommerceRepository()
    products = _seeded_products(repository)
    reviews = repository.list("reviews")
    returns = repository.list("returns")

    for product in products:
        assert (root / product["media"]["primary"]).exists()
        assert (root / product["media"]["care_label"]).exists()
        for view in ("front", "back", "left", "right"):
            assert (root / "assets/mock/catalog" / f"{product['id']}-{view}.png").exists()
    for review in reviews:
        # Reviews created through POST /v1/reviews (Sub-phase 6) can be text-only --
        # media is optional there, unlike the seed script's reviews which always set it.
        if review["media"] is not None:
            assert (root / review["media"]).exists()
    for return_case in returns:
        assert (root / return_case["video"]).exists()
