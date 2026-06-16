"""门店语音点单 Agent CLI Demo。"""

import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _print_cart(cart: list[dict]) -> None:
    if not cart:
        return
    print("\n[购物车草稿]")
    total = 0.0
    for item in cart:
        subtotal = item["price"] * item["qty"]
        total += subtotal
        print(f"  - {item['name']} x{item['qty']}  ¥{subtotal:.1f}")
    print(f"  合计: ¥{total:.1f}")


def main() -> None:
    from agent.graph import build_agent

    agent = build_agent()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("=" * 50)
    print("Retail Voice Agent Demo")
    print("示例: 推荐点无糖饮料 / 第二个来一瓶 / 再来一个可颂")
    print("输入 quit 退出")
    print("=" * 50)

    while True:
        user_input = input("\n你: ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit", "q"}:
            print("再见！")
            break

        result = agent.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
        )

        last_message = result["messages"][-1]
        print(f"\nAgent: {last_message.content}")
        _print_cart(result.get("cart", []))


if __name__ == "__main__":
    main()
