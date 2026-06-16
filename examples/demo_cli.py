"""门店语音点单 Agent CLI Demo。"""

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.session_logger import SessionLogger, build_state_snapshot, extract_turn_trace

load_dotenv(PROJECT_ROOT / ".env")


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


def _short_json(data: object, limit: int = 200) -> str:
    text = json.dumps(data, ensure_ascii=False)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _print_verbose_trace(
    messages: list,
    start_idx: int,
    prev_cart: list[dict],
    prev_recs: list[dict],
    prev_pending: list[dict],
    prev_dialog_state: str,
    new_cart: list[dict],
    new_recs: list[dict],
    new_pending: list[dict],
    new_dialog_state: str,
) -> None:
    new_messages = messages[start_idx:]
    if not new_messages:
        print("\n[verbose] 本轮没有产生新的内部消息")
        return

    print("\n" + "=" * 50)
    print("[verbose] 本轮 Agent 内部流程")
    print("=" * 50)

    step = 1
    for msg in new_messages:
        if isinstance(msg, AIMessage):
            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    print(f"\n步骤 {step}: LLM 决定调用 tool")
                    print(f"  name: {tool_call['name']}")
                    print(f"  args: {_short_json(tool_call['args'], limit=300)}")
                    step += 1
            elif msg.content:
                print(f"\n步骤 {step}: LLM 生成最终回复")
                print(f"  content: {msg.content}")
                step += 1
        elif isinstance(msg, ToolMessage):
            print(f"\n步骤 {step}: tool 执行完毕")
            print(f"  tool_call_id: {msg.tool_call_id}")
            print(f"  result:\n{msg.content}")
            step += 1
        elif isinstance(msg, HumanMessage):
            print(f"\n步骤 {step}: 收到用户输入")
            print(f"  content: {msg.content}")
            step += 1

    print("\n[verbose] 状态变化")
    if prev_cart != new_cart:
        print(f"  cart: {_short_json(prev_cart, limit=300)}")
        print(f"    -> {_short_json(new_cart, limit=300)}")
    else:
        print("  cart: 无变化")

    if prev_recs != new_recs:
        print(f"  last_recommendations: {_short_json(prev_recs, limit=300)}")
        print(f"    -> {_short_json(new_recs, limit=300)}")
    else:
        print("  last_recommendations: 无变化")

    if prev_pending != new_pending:
        print(f"  pending_options: {_short_json(prev_pending, limit=300)}")
        print(f"    -> {_short_json(new_pending, limit=300)}")
    else:
        print("  pending_options: 无变化")

    if prev_dialog_state != new_dialog_state:
        print(f"  dialog_state: {prev_dialog_state} -> {new_dialog_state}")
    else:
        print(f"  dialog_state: {new_dialog_state or 'idle'}")

    print("=" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(description="Retail Voice Agent CLI Demo")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="打印 LLM/tool 调用过程和状态变化，便于调试学习",
    )
    parser.add_argument(
        "--log-dir",
        default=str(PROJECT_ROOT / "logs"),
        help="会话日志保存目录，默认 project/logs",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="关闭会话日志",
    )
    args = parser.parse_args()

    from agent.graph import build_agent

    agent = build_agent()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    logger = None
    if not args.no_log:
        logger = SessionLogger(
            log_dir=Path(args.log_dir),
            session_id=thread_id,
            verbose=args.verbose,
        )

    print("=" * 50)
    print("Retail Voice Agent Demo")
    print("示例: 推荐点无糖饮料 / 第二个来一瓶 / 再来一个可颂")
    if args.verbose:
        print("verbose 模式已开启，将显示 tool 调用过程")
    if logger:
        print(f"会话日志: {logger.log_path}")
    print("输入 quit 退出")
    print("=" * 50)

    turn_index = 0
    try:
        while True:
            user_input = input("\n你: ").strip()
            if not user_input:
                continue
            if user_input.lower() in {"quit", "exit", "q"}:
                print("再见！")
                break

            turn_index += 1
            turn_started_at = datetime.now().isoformat(timespec="seconds")

            prev_state = agent.get_state(config)
            prev_values = prev_state.values if prev_state else {}
            prev_messages = prev_values.get("messages", [])
            prev_cart = list(prev_values.get("cart", []))
            prev_recs = list(prev_values.get("last_recommendations", []))
            prev_pending = list(prev_values.get("pending_options", []))
            prev_dialog_state = prev_values.get("dialog_state", "idle")

            result = agent.invoke(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
            )

            new_cart = list(result.get("cart", []))
            new_recs = list(result.get("last_recommendations", []))
            new_pending = list(result.get("pending_options", []))
            new_dialog_state = result.get("dialog_state", "idle")
            trace = extract_turn_trace(result["messages"], start_idx=len(prev_messages) + 1)

            if args.verbose:
                _print_verbose_trace(
                    result["messages"],
                    start_idx=len(prev_messages) + 1,
                    prev_cart=prev_cart,
                    prev_recs=prev_recs,
                    prev_pending=prev_pending,
                    prev_dialog_state=prev_dialog_state,
                    new_cart=new_cart,
                    new_recs=new_recs,
                    new_pending=new_pending,
                    new_dialog_state=new_dialog_state,
                )

            last_message = result["messages"][-1]
            print(f"\nAgent: {last_message.content}")
            _print_cart(new_cart)

            if logger:
                logger.log_turn(
                    {
                        "turn": turn_index,
                        "timestamp": turn_started_at,
                        "user_input": user_input,
                        "agent_reply": last_message.content,
                        "trace": trace,
                        "state_before": build_state_snapshot(
                            prev_cart, prev_recs, prev_pending, prev_dialog_state
                        ),
                        "state_after": build_state_snapshot(
                            new_cart, new_recs, new_pending, new_dialog_state
                        ),
                    }
                )
    finally:
        if logger:
            logger.finalize()
            print(f"\n日志已保存: {logger.log_path}")


if __name__ == "__main__":
    main()
