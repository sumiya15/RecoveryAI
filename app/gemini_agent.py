from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncIterator

from google import genai

from app.agent import build_agent_input
from app.tools import (
    check_launch_readiness_impl,
    draft_channel_copy_impl,
    extract_tasks_from_brief_impl,
    generate_owner_checklist_impl,
)


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


async def _run_tool(name: str, fn, *args: Any) -> Any:
    await asyncio.sleep(0)
    return fn(*args)


def _gemini_prompt(payload: dict[str, str], tool_results: dict[str, Any]) -> str:
    return f"""
You are Launch Desk, a precise launch-planning agent for engineering teams.
Turn the intake and tool outputs into a concise, structured response with:
Prioritized Plan, Risk Register, Owner Checklist, Launch Copy Suggestions, Follow-up Questions.

Ask follow-up questions when launch date, audience, constraints, assets, owners, success metrics,
rollout strategy, or support readiness are underspecified.

Intake:
{build_agent_input(payload)}

Tool outputs:
{json.dumps(tool_results, indent=2)}
"""


async def stream_gemini_launch_plan(payload: dict[str, str]) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "status", "message": "Starting Launch Desk planning run with Gemini"}

    tools_to_run = [
        (
            "extract_tasks_from_brief",
            extract_tasks_from_brief_impl,
            payload["product_brief"],
            payload["launch_date"],
            payload.get("available_assets", ""),
        ),
        (
            "check_launch_readiness",
            check_launch_readiness_impl,
            payload["product_brief"],
            payload["audience"],
            payload["launch_date"],
            payload.get("constraints", ""),
            payload.get("available_assets", ""),
        ),
        (
            "generate_owner_checklist",
            generate_owner_checklist_impl,
            payload["audience"],
            payload.get("constraints", ""),
        ),
    ]

    tool_results: dict[str, Any] = {}
    for name, fn, *args in tools_to_run:
        yield {"type": "tool_progress", "status": "started", "tool": name}
        tool_results[name] = await _run_tool(name, fn, *args)
        yield {"type": "tool_progress", "status": "completed", "tool": name}

    copy_results = {}
    for channel in ["email", "changelog", "social", "in_app"]:
        name = f"draft_channel_copy.{channel}"
        yield {"type": "tool_progress", "status": "started", "tool": name}
        copy_results[channel] = draft_channel_copy_impl(
            payload["product_brief"],
            payload["audience"],
            channel,
        )
        yield {"type": "tool_progress", "status": "completed", "tool": name}
    tool_results["draft_channel_copy"] = copy_results

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    try:
        stream = client.models.generate_content_stream(
            model=os.getenv("GEMINI_MODEL", GEMINI_MODEL),
            contents=_gemini_prompt(payload, tool_results),
        )
        for chunk in stream:
            if chunk.text:
                yield {"type": "text_delta", "delta": chunk.text}
                await asyncio.sleep(0)
    finally:
        client.close()

    yield {"type": "done", "message": "Launch plan complete"}
