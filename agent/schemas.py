from typing import Literal

from pydantic import BaseModel, Field


class Product(BaseModel):
    sku_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    category: str
    tags: list[str] = Field(default_factory=list)
    price: float
    in_stock: bool = True
    attributes: dict = Field(default_factory=dict)


class CartItem(BaseModel):
    sku_id: str
    name: str
    qty: int
    price: float


class CartAction(BaseModel):
    op: Literal["add", "remove", "update"]
    sku_id: str
    name: str
    qty: int
    price: float
