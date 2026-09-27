from __future__ import annotations

import os
from typing import Any, AsyncIterator

from agents import Agent, RunConfig, Runner, trace

from app.tools import (
    check_launch_readiness,
    draft_channel_copy,
    extract_tasks_from_brief,
    generate_owner_checklist,
)


MODEL = os.getenv("LAUNCH_DESK_MODEL", "gpt-5.6-terra")

launch_agent = Agent(
    name="Launch Desk",
    model=MODEL,
    instructions=(
        "You are Launch Desk, a precise launch-planning agent for engineering teams. "
        "Turn rough product launch inputs into an actionable release plan. "
        "You must use the provided tools before writing the final plan. "
        "Produce a concise, structured response with these sections: Prioritized Plan, "
        "Risk Register, Owner Checklist, Launch Copy Suggestions, Follow-up Questions. "
        "Ask follow-up questions when launch date, audience, constraints, assets, owners, "
        "success metrics, rollout strategy, or support readiness are underspecified. "
        "Be pragmatic, call out sequencing, and distinguish blockers from nice-to-haves."
    ),
    tools=[
        extract_tasks_from_brief,
        check_launch_readiness,
        generate_owner_checklist,
        draft_channel_copy,
    ],
)


def build_agent_input(payload: dict[str, str]) -> str:
    return f"""
Create a launch plan from this intake.

Product brief:
{payload["product_brief"]}

Audience:
{payload["audience"]}

Launch date:
{payload["launch_date"]}

Constraints:
{payload.get("constraints") or "Not provided"}

Available assets:
{payload.get("available_assets") or "Not provided"}

Before finalizing, use the tools to extract tasks, check readiness, create an owner checklist,
and draft copy for at least email, changelog, social, and in_app channels.
"""


def _tool_name(event: Any) -> str:
    item = getattr(event, "item", None)
    raw_item = getattr(item, "raw_item", None)
    return (
        getattr(raw_item, "name", None)
        or getattr(item, "name", None)
        or getattr(event, "name", None)
        or "tool"
    )


async def stream_launch_plan(payload: dict[str, str]) -> AsyncIterator[dict[str, Any]]:
    run_config = RunConfig(
        workflow_name="Launch Desk Planning",
        trace_metadata={"app": "launch-desk", "surface": "api"},
    )

    yield {"type": "status", "message": "Starting Launch Desk planning run"}

    with trace("Launch Desk Planning", metadata={"audience": payload.get("audience", "")}):
        result = Runner.run_streamed(
            launch_agent,
            input=build_agent_input(payload),
            run_config=run_config,
        )

        async for event in result.stream_events():
            if event.type == "raw_response_event":
                data = getattr(event, "data", None)
                if getattr(data, "type", "") == "response.output_text.delta":
                    delta = getattr(data, "delta", "")
                    if delta:
                        yield {"type": "text_delta", "delta": delta}
                continue

            if event.type == "run_item_stream_event":
                if event.name == "tool_called":
                    yield {
                        "type": "tool_progress",
                        "status": "started",
                        "tool": _tool_name(event),
                    }
                elif event.name == "tool_output":
                    yield {
                        "type": "tool_progress",
                        "status": "completed",
                        "tool": _tool_name(event),
                    }
                continue

            if event.type == "agent_updated_stream_event":
                yield {"type": "status", "message": f"Agent updated: {event.new_agent.name}"}

    yield {"type": "done", "message": "Launch plan complete"}
