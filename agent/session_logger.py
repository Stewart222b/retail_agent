from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage


def extract_turn_trace(messages: list, start_idx: int) -> list[dict]:
    steps: list[dict] = []
    for msg in messages[start_idx:]:
        if isinstance(msg, AIMessage):
            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    steps.append(
                        {
                            "type": "tool_call",
                            "name": tool_call["name"],
                            "args": tool_call["args"],
                        }
                    )
            elif msg.content:
                steps.append({"type": "agent_reply", "content": msg.content})
        elif isinstance(msg, ToolMessage):
            steps.append(
                {
                    "type": "tool_result",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                }
            )
    return steps


def build_state_snapshot(
    cart: list[dict],
    last_recommendations: list[dict],
    pending_options: list[dict],
    dialog_state: str,
) -> dict:
    return {
        "cart": cart,
        "last_recommendations": last_recommendations,
        "pending_options": pending_options,
        "dialog_state": dialog_state or "idle",
    }


class SessionLogger:
    def __init__(self, log_dir: Path, session_id: str, verbose: bool = False) -> None:
        self.session_id = session_id
        self.verbose = verbose
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.turns: list[dict] = []

        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = self.log_dir / f"session_{timestamp}_{session_id[:8]}.json"

    def log_turn(self, turn: dict) -> None:
        self.turns.append(turn)
        self._flush()

    def finalize(self) -> None:
        self._flush()

    def _flush(self) -> None:
        payload = {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "verbose": self.verbose,
            "turn_count": len(self.turns),
            "turns": self.turns,
        }
        self.log_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
