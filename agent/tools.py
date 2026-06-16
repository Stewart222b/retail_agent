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


def _set_pending(recs: list[dict], dialog_state: str = "confirming") -> dict:
    return {
        "last_recommendations": recs,
        "pending_options": recs,
        "dialog_state": dialog_state if recs else "idle",
    }


def _clear_pending() -> dict:
    return {"pending_options": [], "dialog_state": "idle"}


def _resolve_pending_index(pending: list[dict], index: int, selection: str) -> int | None:
    if index >= 1 and index <= len(pending):
        return index - 1

    if not selection.strip():
        return None

    query = selection.strip().lower()
    scored: list[tuple[int, int]] = []
    for idx, item in enumerate(pending):
        product = catalog.get_product_by_id(item["sku_id"])
        if not product:
            continue
        haystack = " ".join([product.name, *product.aliases]).lower()
        score = 0
        if query in product.name.lower():
            score += 5
        if any(query in alias.lower() for alias in product.aliases):
            score += 4
        if query in haystack:
            score += 2
        if score > 0:
            scored.append((score, idx))

    if not scored:
        return None
    scored.sort(key=lambda item: -item[0])
    return scored[0][1]


@tool
def search_products(query: str, category: str = "", limit: int = 5, runtime: ToolRuntime = None) -> Command:
    """按关键词搜索商品，可选按品类过滤。适合处理具体商品名或模糊描述。"""
    products = catalog.search_products(query, category=category or None, limit=limit)
    recs = [_product_to_dict(product) for product in products]
    content = _format_products(products)
    update = _set_pending(recs) if recs else {"dialog_state": "idle"}
    update["messages"] = [ToolMessage(content=content, tool_call_id=runtime.tool_call_id)]
    return Command(update=update)


@tool
def filter_by_tags(tags: list[str], limit: int = 5, runtime: ToolRuntime = None) -> Command:
    """按标签筛选商品。常见标签：无糖、低糖、低卡、零卡、热销、适合儿童、早餐、含咖啡因、新品。"""
    products = catalog.filter_by_tags(tags, limit=limit)
    recs = [_product_to_dict(product) for product in products]
    content = _format_products(products)
    update = _set_pending(recs) if recs else {"dialog_state": "idle"}
    update["messages"] = [ToolMessage(content=content, tool_call_id=runtime.tool_call_id)]
    return Command(update=update)


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
def get_pending_options(runtime: ToolRuntime) -> str:
    """查看当前待用户确认的商品列表。"""
    pending = runtime.state.get("pending_options", [])
    if not pending:
        return "当前没有待确认商品。"
    lines = []
    for idx, item in enumerate(pending, start=1):
        lines.append(f"{idx}. [{item['sku_id']}] {item['name']} ¥{item['price']}")
    return "\n".join(lines)


@tool
def confirm_pending_option(
    index: int = 0,
    selection: str = "",
    qty: int = 1,
    runtime: ToolRuntime = None,
) -> Command:
    """从 pending_options 中确认加购。支持序号 index 或模糊名称 selection（如“拿铁”“奶铁”）。"""
    pending = runtime.state.get("pending_options", [])
    if not pending:
        fallback = runtime.state.get("last_recommendations", [])
        if fallback:
            pending = fallback
        else:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content="当前没有待确认商品，请先搜索或让我推荐。",
                            tool_call_id=runtime.tool_call_id,
                        )
                    ]
                }
            )

    resolved = _resolve_pending_index(pending, index, selection)
    if resolved is None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="无法从待确认列表中匹配该商品，请说第几个或更明确的名称。",
                        tool_call_id=runtime.tool_call_id,
                    )
                ]
            }
        )

    selected = pending[resolved]
    product = catalog.get_product_by_id(selected["sku_id"])
    if not product:
        return Command(
            update={
                "messages": [
                    ToolMessage(content=f"商品不存在: {selected['sku_id']}", tool_call_id=runtime.tool_call_id)
                ]
            }
        )

    cart = _upsert_cart(
        runtime.state.get("cart", []),
        product.sku_id,
        product.name,
        product.price,
        qty,
        "add",
    )
    return Command(
        update={
            "cart": cart,
            **_clear_pending(),
            "messages": [
                ToolMessage(
                    content=f"已提案加入 {product.name} x{qty}",
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )


@tool
def add_recommendation_by_index(index: int, qty: int = 1, runtime: ToolRuntime = None) -> Command:
    """从待确认/推荐列表中按序号加购。index=1 表示第一个，index=2 表示第二个。"""
    return confirm_pending_option.invoke(
        {"index": index, "selection": "", "qty": qty, "runtime": runtime}
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

    update = {
        "cart": cart,
        "messages": [ToolMessage(content=action_text, tool_call_id=runtime.tool_call_id)],
    }
    if op == "add":
        update.update(_clear_pending())
    return Command(update=update)


ALL_TOOLS = [
    search_products,
    filter_by_tags,
    get_product_info,
    get_cart_snapshot,
    get_pending_options,
    confirm_pending_option,
    add_recommendation_by_index,
    propose_cart_action,
]
