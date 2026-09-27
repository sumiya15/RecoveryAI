from __future__ import annotations

import argparse
import json
import sys

import httpx


PAYLOAD = {
    "product_brief": (
        "Launch Desk is a planning assistant for engineering teams that turns rough "
        "release ideas into launch plans, readiness checks, risk registers, owner "
        "checklists, and launch copy."
    ),
    "audience": "engineering managers and product-minded tech leads",
    "launch_date": "2026-09-30",
    "constraints": "two-week timeline, limited design support, API docs must be ready",
    "available_assets": "beta notes, product screenshots, draft changelog",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/plan")
    args = parser.parse_args()

    saw_tool = False
    saw_delta = False

    with httpx.stream("POST", args.url, json=PAYLOAD, timeout=120) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            event = json.loads(line.removeprefix("data: "))
            print(event)
            if event.get("type") == "tool_progress":
                saw_tool = True
            if event.get("type") == "text_delta":
                saw_delta = True
            if saw_tool and saw_delta:
                print("Verified: received at least one tool_progress event and one text_delta event.")
                return 0

    print(
        f"Verification failed: saw_tool={saw_tool}, saw_text_delta={saw_delta}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
