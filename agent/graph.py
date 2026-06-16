import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import START, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import Annotated, TypedDict

from agent.prompts import SYSTEM_PROMPT
from agent.tools import ALL_TOOLS


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    cart: list[dict]
    last_recommendations: list[dict]
    pending_options: list[dict]
    dialog_state: str


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        temperature=0.3,
    )


def _build_context_message(state: AgentState) -> SystemMessage | None:
    pending = state.get("pending_options") or []
    if not pending:
        return None

    lines = []
    for idx, item in enumerate(pending, start=1):
        lines.append(f"{idx}. [{item['sku_id']}] {item['name']} ¥{item['price']}")

    dialog_state = state.get("dialog_state", "idle")
    return SystemMessage(
        content=(
            f"【会话上下文】dialog_state={dialog_state}\n"
            "当前有待确认商品（pending_options），用户若在确认/选择，"
            "请优先调用 confirm_pending_option，不要重新 search。\n"
            + "\n".join(lines)
        )
    )


def build_agent():
    llm = _build_llm().bind_tools(ALL_TOOLS)

    def agent_node(state: AgentState) -> dict:
        messages = list(state["messages"])
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]
        elif not messages[0].content.startswith("你是门店里的语音点单助手"):
            messages = [SystemMessage(content=SYSTEM_PROMPT), *messages]

        context_message = _build_context_message(state)
        if context_message:
            insert_at = 1
            for idx, msg in enumerate(messages):
                if isinstance(msg, HumanMessage):
                    insert_at = idx
                    break
            messages = messages[:insert_at] + [context_message] + messages[insert_at:]

        response = llm.invoke(messages)
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=MemorySaver())
