from typing import Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from agent import catalog


def _product_to_dict(product) -> dict:
    return {
        "sku_id": product.sku_id,
        "name": product.name,
        "price": product.price,
        "category": product.category,
        "tags": product.tags,
    }


def _format_products(products) -> str:
    if not products:
        return "没有找到相关商品。"
    lines = []
    for idx, product in enumerate(products, start=1):
        tags = "、".join(product.tags[:3])
        lines.append(f"{idx}. [{product.sku_id}] {product.name}（¥{product.price}，{tags}）")
    return "\n".join(lines)


def _upsert_cart(cart: list[dict], sku_id: str, name: str, price: float, qty: int, op: str) -> list[dict]:
    cart = [dict(item) for item in cart]
    if op == "add":
        for item in cart:
            if item["sku_id"] == sku_id:
                item["qty"] += qty
                return cart
        cart.append({"sku_id": sku_id, "name": name, "qty": qty, "price": price})
        return cart

    if op == "remove":
        return [item for item in cart if item["sku_id"] != sku_id]

    if op == "update":
        for item in cart:
            if item["sku_id"] == sku_id:
                item["qty"] = qty
                return cart
        cart.append({"sku_id": sku_id, "name": name, "qty": qty, "price": price})
        return cart

    return cart


@tool
def search_products(query: str, category: str = "", limit: int = 5, runtime: ToolRuntime = None) -> Command:
    """按关键词搜索商品，可选按品类过滤。适合处理具体商品名或模糊描述。"""
    products = catalog.search_products(query, category=category or None, limit=limit)
    recs = [_product_to_dict(product) for product in products]
    content = _format_products(products)
    return Command(
        update={
            "last_recommendations": recs,
            "messages": [ToolMessage(content=content, tool_call_id=runtime.tool_call_id)],
        }
    )


@tool
def filter_by_tags(tags: list[str], limit: int = 5, runtime: ToolRuntime = None) -> Command:
    """按标签筛选商品。常见标签：无糖、低糖、低卡、零卡、热销、适合儿童、早餐、含咖啡因、新品。"""
    products = catalog.filter_by_tags(tags, limit=limit)
    recs = [_product_to_dict(product) for product in products]
    content = _format_products(products)
    return Command(
        update={
            "last_recommendations": recs,
            "messages": [ToolMessage(content=content, tool_call_id=runtime.tool_call_id)],
        }
    )


@tool
def get_product_info(sku_id: str) -> str:
    """查看单个商品的详细信息。"""
    product = catalog.get_product_by_id(sku_id)
    if not product:
        return f"未找到商品: {sku_id}"
    tags = "、".join(product.tags)
    attrs = "，".join(f"{k}:{v}" for k, v in product.attributes.items())
    stock = "有货" if product.in_stock else "缺货"
    return f"{product.name}（{product.sku_id}），{product.category}，¥{product.price}，{tags}，{attrs}，{stock}"


@tool
def get_cart_snapshot(runtime: ToolRuntime) -> str:
    """查看当前购物车草稿内容。"""
    cart = runtime.state.get("cart", [])
    if not cart:
        return "购物车目前是空的。"
    lines = []
    total = 0.0
    for item in cart:
        subtotal = item["price"] * item["qty"]
        total += subtotal
        lines.append(f"- {item['name']} x{item['qty']} = ¥{subtotal:.1f}")
    lines.append(f"合计: ¥{total:.1f}")
    return "\n".join(lines)


@tool
def add_recommendation_by_index(index: int, qty: int = 1, runtime: ToolRuntime = None) -> Command:
    """从上一轮推荐列表中按序号加购。index=1 表示第一个，index=2 表示第二个。"""
    recs = runtime.state.get("last_recommendations", [])
    if not recs:
        return Command(
            update={
                "messages": [
                    ToolMessage(content="当前没有可选择的推荐商品，请先让我为您推荐。", tool_call_id=runtime.tool_call_id)
                ]
            }
        )
    if index < 1 or index > len(recs):
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"序号无效，请输入 1 到 {len(recs)} 之间的数字。",
                        tool_call_id=runtime.tool_call_id,
                    )
                ]
            }
        )

    selected = recs[index - 1]
    return propose_cart_action.invoke(
        {"op": "add", "sku_id": selected["sku_id"], "qty": qty, "runtime": runtime}
    )


@tool
def propose_cart_action(
    op: Literal["add", "remove", "update"],
    sku_id: str,
    qty: int = 1,
    runtime: ToolRuntime = None,
) -> Command:
    """提案修改购物车草稿。op=add 加购，remove 移除，update 修改数量。顾客确认购买后再调用。"""
    product = catalog.get_product_by_id(sku_id)
    if not product:
        return Command(
            update={
                "messages": [
                    ToolMessage(content=f"商品不存在: {sku_id}", tool_call_id=runtime.tool_call_id)
                ]
            }
        )
    if not product.in_stock:
        return Command(
            update={
                "messages": [
                    ToolMessage(content=f"{product.name} 当前缺货。", tool_call_id=runtime.tool_call_id)
                ]
            }
        )
    if qty <= 0 and op != "remove":
        return Command(
            update={
                "messages": [
                    ToolMessage(content="数量必须大于 0。", tool_call_id=runtime.tool_call_id)
                ]
            }
        )

    cart = _upsert_cart(
        runtime.state.get("cart", []),
        product.sku_id,
        product.name,
        product.price,
        qty,
        op,
    )
    cart = [item for item in cart if item.get("qty", 0) > 0]

    if op == "add":
        action_text = f"已提案加入 {product.name} x{qty}"
    elif op == "remove":
        action_text = f"已提案移除 {product.name}"
    else:
        action_text = f"已提案将 {product.name} 数量改为 {qty}"

    return Command(
        update={
            "cart": cart,
            "messages": [ToolMessage(content=action_text, tool_call_id=runtime.tool_call_id)],
        }
    )


ALL_TOOLS = [
    search_products,
    filter_by_tags,
    get_product_info,
    get_cart_snapshot,
    add_recommendation_by_index,
    propose_cart_action,
]
