from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from agents import function_tool


def _split_items(text: str) -> list[str]:
    parts = [
        piece.strip(" -\t\r\n")
        for raw in text.replace(";", "\n").split("\n")
        for piece in raw.split(",")
    ]
    return [part for part in parts if part]


def extract_tasks_from_brief_impl(product_brief: str, launch_date: str, available_assets: str) -> dict:
    assets = _split_items(available_assets)
    tasks = [
        {
            "task": "Confirm launch narrative and top customer problem",
            "priority": "P0",
            "owner": "Product",
            "due": "T-10 business days",
        },
        {
            "task": "Freeze release scope and rollback criteria",
            "priority": "P0",
            "owner": "Engineering",
            "due": "T-7 business days",
        },
        {
            "task": "Prepare customer-facing launch copy",
            "priority": "P1",
            "owner": "Marketing",
            "due": "T-5 business days",
        },
        {
            "task": "Run launch readiness review",
            "priority": "P0",
            "owner": "Launch lead",
            "due": "T-3 business days",
        },
    ]
    if not assets:
        tasks.append(
            {
                "task": "Create missing launch assets: screenshots, FAQ, support notes, and demo script",
                "priority": "P0",
                "owner": "Product marketing",
                "due": "T-6 business days",
            }
        )
    if any(word in product_brief.lower() for word in ["api", "developer", "sdk", "integration"]):
        tasks.append(
            {
                "task": "Publish developer docs, migration notes, and sample code",
                "priority": "P0",
                "owner": "Developer relations",
                "due": "T-4 business days",
            }
        )
    return {"launch_date": launch_date, "assets_detected": assets, "tasks": tasks}


@function_tool
def extract_tasks_from_brief(product_brief: str, launch_date: str, available_assets: str) -> dict:
    """Extract practical launch tasks from a product brief and known assets."""
    return extract_tasks_from_brief_impl(product_brief, launch_date, available_assets)


def check_launch_readiness_impl(
    product_brief: str,
    audience: str,
    launch_date: str,
    constraints: str,
    available_assets: str,
) -> dict:
    """Score launch readiness against a simple release rubric."""
    checks = []
    fields = {
        "Brief explains product value": len(product_brief.strip()) >= 80,
        "Audience is defined": len(audience.strip()) >= 8,
        "Launch date is present": bool(launch_date.strip()),
        "Constraints are documented": bool(constraints.strip()),
        "At least two launch assets exist": len(_split_items(available_assets)) >= 2,
    }
    for name, passed in fields.items():
        checks.append({"check": name, "status": "pass" if passed else "needs_work"})

    score = round(sum(1 for item in checks if item["status"] == "pass") / len(checks), 2)
    if score >= 0.8:
        rating = "green"
    elif score >= 0.55:
        rating = "yellow"
    else:
        rating = "red"

    return {
        "readiness_score": score,
        "rating": rating,
        "checks": checks,
        "recommendation": "Launchable with normal controls" if rating == "green" else "Close the gaps before broad launch",
    }


@function_tool
def check_launch_readiness(
    product_brief: str,
    audience: str,
    launch_date: str,
    constraints: str,
    available_assets: str,
) -> dict:
    """Score launch readiness against a simple release rubric."""
    return check_launch_readiness_impl(
        product_brief,
        audience,
        launch_date,
        constraints,
        available_assets,
    )


@function_tool
def generate_owner_checklist(audience: str, constraints: str) -> dict:
    """Generate owner-specific launch checklist items."""
    return generate_owner_checklist_impl(audience, constraints)


def generate_owner_checklist_impl(audience: str, constraints: str) -> dict:
    checklist = {
        "Engineering": [
            "Confirm release branch, migration plan, monitoring dashboards, and rollback owner.",
            "Run smoke tests on the exact build planned for launch.",
        ],
        "Product": [
            "Approve launch scope, positioning, success metrics, and known limitations.",
            "Prepare follow-up decision points for launch day plus one week.",
        ],
        "Marketing": [
            f"Tailor announcement language for {audience}.",
            "Prepare email, social, changelog, and in-product announcement variants.",
        ],
        "Support": [
            "Publish internal FAQ and escalation paths.",
            "Tag launch-related tickets for first-week reporting.",
        ],
    }
    if constraints.strip():
        checklist["Launch lead"] = [f"Track constraint mitigation: {constraints.strip()}"]
    return {"checklist": checklist}


def draft_channel_copy_impl(
    product_brief: str,
    audience: str,
    channel: Literal["email", "changelog", "social", "in_app"],
) -> dict:
    short_value = product_brief.strip().split(".")[0][:180]
    variants = {
        "email": {
            "subject": "New: a faster way to ship with confidence",
            "body": f"We built this for {audience}: {short_value}. The release is designed to help teams move from intent to action with less coordination drag.",
        },
        "changelog": {
            "title": "Launch Desk is now available",
            "body": f"Launch Desk helps {audience} convert rough launch ideas into prioritized plans, risks, checklists, and channel-ready copy.",
        },
        "social": {
            "body": f"Launching soon: Launch Desk helps {audience} turn a rough release idea into an actionable plan, checklist, and launch copy.",
        },
        "in_app": {
            "body": "Plan your launch, identify risks, and assign owners before release day.",
        },
    }
    return {"channel": channel, "copy": variants[channel]}


@function_tool
def draft_channel_copy(
    product_brief: str,
    audience: str,
    channel: Literal["email", "changelog", "social", "in_app"],
) -> dict:
    """Draft channel-specific launch copy."""
    return draft_channel_copy_impl(product_brief, audience, channel)


def days_until_launch(launch_date: str) -> int | None:
    try:
        parsed = datetime.fromisoformat(launch_date).date()
    except ValueError:
        return None
    return (parsed - date.today()).days
