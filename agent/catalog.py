import json
from pathlib import Path

from agent.schemas import Product

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "catalog" / "products.json"


def load_catalog() -> list[Product]:
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return [Product.model_validate(item) for item in raw]


def get_product_by_id(sku_id: str) -> Product | None:
    for product in load_catalog():
        if product.sku_id == sku_id:
            return product
    return None


def search_products(query: str, category: str | None = None, limit: int = 10) -> list[Product]:
    query = query.strip().lower()
    if not query:
        return []

    scored: list[tuple[int, Product]] = []
    for product in load_catalog():
        if category and product.category != category:
            continue

        haystack = " ".join([product.name, product.category, *product.aliases, *product.tags]).lower()
        score = 0
        if query in product.name.lower():
            score += 5
        if any(query in alias.lower() for alias in product.aliases):
            score += 4
        if query in haystack:
            score += 2
        if any(token in haystack for token in query.split()):
            score += 1

        if score > 0 and product.in_stock:
            scored.append((score, product))

    scored.sort(key=lambda item: (-item[0], item[1].price))
    return [product for _, product in scored[:limit]]


def filter_by_tags(tags: list[str], limit: int = 5) -> list[Product]:
    if not tags:
        return []

    wanted = {tag.strip() for tag in tags if tag.strip()}
    matched: list[tuple[int, Product]] = []

    for product in load_catalog():
        if not product.in_stock:
            continue
        overlap = wanted.intersection(set(product.tags))
        if overlap:
            matched.append((len(overlap), product))

    matched.sort(key=lambda item: (-item[0], -item[1].price))
    return [product for _, product in matched[:limit]]
