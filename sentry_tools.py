"""
Sentry API tools for querying issues, events, and stacktraces.

Provides tools for the SRE agent to interact with Sentry's API
to investigate and understand errors.
"""

import hashlib
import hmac
import json
from typing import Any, Optional

import httpx

from sentry_context import SentryContext


# =============================================================================
# Webhook Signature Verification
# =============================================================================


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
) -> bool:
    """
    Verify Sentry webhook signature using HMAC-SHA256.

    Args:
        payload: Raw request body bytes
        signature: Value from Sentry-Hook-Signature header
        secret: Webhook secret from Sentry integration settings

    Returns:
        True if signature is valid, False otherwise
    """
    if not secret or not signature:
        return False

    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# =============================================================================
# Webhook Payload Parsing
# =============================================================================


def parse_issue_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Parse an issue webhook payload from Sentry.

    Handles webhooks triggered by issue.created, issue.resolved, etc.

    Args:
        payload: Parsed JSON webhook payload

    Returns:
        Dictionary with extracted issue information:
        - issue_id: Sentry issue ID
        - project_slug: Project identifier
        - title: Issue title
        - culprit: Location where error occurred
        - level: Error level (error, warning, etc.)
        - first_seen: When issue was first seen
        - last_seen: When issue was last seen
        - count: Number of events
    """
    data = payload.get("data", {})
    issue = data.get("issue", data)  # issue might be nested or at top level

    return {
        "issue_id": str(issue.get("id", "")),
        "project_slug": issue.get("project", {}).get("slug", ""),
        "title": issue.get("title", ""),
        "culprit": issue.get("culprit", ""),
        "level": issue.get("level", "error"),
        "first_seen": issue.get("firstSeen", ""),
        "last_seen": issue.get("lastSeen", ""),
        "count": issue.get("count", 0),
        "short_id": issue.get("shortId", ""),
        "metadata": issue.get("metadata", {}),
    }


def parse_event_alert_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Parse an event alert webhook payload from Sentry.

    Handles webhooks triggered by alert rules firing.

    Args:
        payload: Parsed JSON webhook payload

    Returns:
        Dictionary with extracted alert information:
        - issue_id: Sentry issue ID
        - project_slug: Project identifier
        - event_id: Specific event ID that triggered the alert
        - title: Event/issue title
        - message: Alert message
        - level: Error level
        - url: Link to the issue in Sentry
    """
    data = payload.get("data", {})
    event = data.get("event", {})
    issue_url = event.get("issue_url", "") or event.get("web_url", "")

    # Extract issue ID from URL if not directly available
    issue_id = event.get("issue_id", "")
    if not issue_id and "/issues/" in issue_url:
        # Extract from URL like https://sentry.io/organizations/org/issues/123/
        parts = issue_url.split("/issues/")
        if len(parts) > 1:
            issue_id = parts[1].strip("/").split("/")[0]

    return {
        "issue_id": str(issue_id),
        "event_id": event.get("event_id", ""),
        "project_slug": event.get("project", "") or data.get("project_slug", ""),
        "title": event.get("title", ""),
        "message": event.get("message", ""),
        "level": event.get("level", "error"),
        "url": issue_url,
        "timestamp": event.get("timestamp", ""),
        "environment": event.get("environment", ""),
    }


# =============================================================================
# Sentry API Tools
# =============================================================================


def sentry_get_issue(ctx: SentryContext, issue_id: str) -> str:
    """
    Get issue details from Sentry.

    Args:
        ctx: Sentry context with authentication
        issue_id: Sentry issue ID

    Returns:
        JSON with issue details or error message
    """
    try:
        url = ctx.get_issue_url(issue_id)

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=ctx.get_headers())

        if response.status_code == 404:
            return json.dumps({"error": f"Issue not found: {issue_id}"})

        if response.status_code != 200:
            return json.dumps({
                "error": f"Sentry API error: {response.status_code}",
                "detail": response.text[:500],
            })

        data = response.json()

        return json.dumps({
            "issue_id": str(data.get("id")),
            "short_id": data.get("shortId"),
            "title": data.get("title"),
            "culprit": data.get("culprit"),
            "level": data.get("level"),
            "status": data.get("status"),
            "first_seen": data.get("firstSeen"),
            "last_seen": data.get("lastSeen"),
            "count": data.get("count"),
            "user_count": data.get("userCount"),
            "project": data.get("project", {}).get("slug"),
            "platform": data.get("platform"),
            "metadata": data.get("metadata", {}),
            "type": data.get("type"),
            "permalink": data.get("permalink"),
        })

    except httpx.TimeoutException:
        return json.dumps({"error": "Request timed out"})
    except Exception as e:
        return json.dumps({"error": f"Failed to get issue: {e}"})


def sentry_get_latest_event(ctx: SentryContext, issue_id: str) -> str:
    """
    Get the latest event for an issue with full stacktrace.

    Args:
        ctx: Sentry context with authentication
        issue_id: Sentry issue ID

    Returns:
        JSON with event details including stacktrace
    """
    try:
        url = ctx.get_latest_event_url(issue_id)

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=ctx.get_headers())

        if response.status_code == 404:
            return json.dumps({"error": f"No events found for issue: {issue_id}"})

        if response.status_code != 200:
            return json.dumps({
                "error": f"Sentry API error: {response.status_code}",
                "detail": response.text[:500],
            })

        data = response.json()

        # Extract stacktrace from exception entries
        stacktraces = []
        entries = data.get("entries", [])

        for entry in entries:
            if entry.get("type") == "exception":
                exc_data = entry.get("data", {})
                for exc_value in exc_data.get("values", []):
                    exc_info = {
                        "type": exc_value.get("type"),
                        "value": exc_value.get("value"),
                        "module": exc_value.get("module"),
                        "frames": [],
                    }

                    stacktrace = exc_value.get("stacktrace", {})
                    for frame in stacktrace.get("frames", []):
                        exc_info["frames"].append({
                            "filename": frame.get("filename"),
                            "abs_path": frame.get("absPath"),
                            "function": frame.get("function"),
                            "lineno": frame.get("lineNo"),
                            "colno": frame.get("colNo"),
                            "context": frame.get("context", []),
                            "in_app": frame.get("inApp", False),
                            "vars": frame.get("vars", {}),
                        })

                    stacktraces.append(exc_info)

        # Extract context/tags/extra
        contexts = data.get("contexts", {})
        tags = data.get("tags", [])
        extra = data.get("context", {})

        return json.dumps({
            "event_id": data.get("eventID"),
            "issue_id": str(issue_id),
            "title": data.get("title"),
            "message": data.get("message"),
            "level": data.get("level"),
            "platform": data.get("platform"),
            "timestamp": data.get("dateCreated"),
            "environment": data.get("environment"),
            "release": data.get("release", {}).get("version") if data.get("release") else None,
            "stacktraces": stacktraces,
            "tags": {tag.get("key"): tag.get("value") for tag in tags},
            "contexts": {
                k: v for k, v in contexts.items()
                if k in ("browser", "os", "device", "runtime", "app")
            },
            "extra": extra,
        })

    except httpx.TimeoutException:
        return json.dumps({"error": "Request timed out"})
    except Exception as e:
        return json.dumps({"error": f"Failed to get event: {e}"})


def sentry_get_issue_events(
    ctx: SentryContext,
    issue_id: str,
    limit: int = 10,
) -> str:
    """
    List events for an issue.

    Args:
        ctx: Sentry context with authentication
        issue_id: Sentry issue ID
        limit: Maximum number of events to return (default: 10, max: 100)

    Returns:
        JSON with list of events
    """
    try:
        limit = min(max(limit, 1), 100)
        url = ctx.get_issue_events_url(issue_id)

        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                url,
                headers=ctx.get_headers(),
                params={"limit": limit},
            )

        if response.status_code == 404:
            return json.dumps({"error": f"Issue not found: {issue_id}"})

        if response.status_code != 200:
            return json.dumps({
                "error": f"Sentry API error: {response.status_code}",
                "detail": response.text[:500],
            })

        data = response.json()

        events = []
        for event in data:
            events.append({
                "event_id": event.get("eventID"),
                "title": event.get("title"),
                "message": event.get("message"),
                "timestamp": event.get("dateCreated"),
                "environment": event.get("environment"),
                "user": event.get("user", {}).get("email") if event.get("user") else None,
            })

        return json.dumps({
            "issue_id": str(issue_id),
            "events": events,
            "count": len(events),
        })

    except httpx.TimeoutException:
        return json.dumps({"error": "Request timed out"})
    except Exception as e:
        return json.dumps({"error": f"Failed to get events: {e}"})


def sentry_list_project_issues(
    ctx: SentryContext,
    project_slug: str,
    query: Optional[str] = None,
    limit: int = 25,
) -> str:
    """
    List recent issues for a project.

    Args:
        ctx: Sentry context with authentication
        project_slug: Sentry project slug
        query: Optional search query (Sentry search syntax)
        limit: Maximum number of issues to return (default: 25, max: 100)

    Returns:
        JSON with list of issues
    """
    try:
        limit = min(max(limit, 1), 100)
        url = ctx.get_project_issues_url(project_slug)

        params: dict[str, Any] = {"limit": limit}
        if query:
            params["query"] = query

        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                url,
                headers=ctx.get_headers(),
                params=params,
            )

        if response.status_code == 404:
            return json.dumps({"error": f"Project not found: {project_slug}"})

        if response.status_code != 200:
            return json.dumps({
                "error": f"Sentry API error: {response.status_code}",
                "detail": response.text[:500],
            })

        data = response.json()

        issues = []
        for issue in data:
            issues.append({
                "issue_id": str(issue.get("id")),
                "short_id": issue.get("shortId"),
                "title": issue.get("title"),
                "culprit": issue.get("culprit"),
                "level": issue.get("level"),
                "status": issue.get("status"),
                "first_seen": issue.get("firstSeen"),
                "last_seen": issue.get("lastSeen"),
                "count": issue.get("count"),
            })

        return json.dumps({
            "project": project_slug,
            "issues": issues,
            "count": len(issues),
        })

    except httpx.TimeoutException:
        return json.dumps({"error": "Request timed out"})
    except Exception as e:
        return json.dumps({"error": f"Failed to list issues: {e}"})


# =============================================================================
# Tool Execution Router
# =============================================================================


def execute_sentry_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    ctx: SentryContext,
) -> str:
    """
    Execute a Sentry tool and return its result.

    Args:
        tool_name: Name of the tool to execute
        tool_input: Input parameters for the tool
        ctx: Sentry context

    Returns:
        JSON string with result or error
    """
    if tool_name == "sentry_get_issue":
        return sentry_get_issue(ctx, tool_input["issue_id"])

    elif tool_name == "sentry_get_latest_event":
        return sentry_get_latest_event(ctx, tool_input["issue_id"])

    elif tool_name == "sentry_get_issue_events":
        return sentry_get_issue_events(
            ctx,
            tool_input["issue_id"],
            tool_input.get("limit", 10),
        )

    elif tool_name == "sentry_list_project_issues":
        return sentry_list_project_issues(
            ctx,
            tool_input["project_slug"],
            tool_input.get("query"),
            tool_input.get("limit", 25),
        )

    else:
        return json.dumps({"error": f"Unknown Sentry tool: {tool_name}"})


# =============================================================================
# Tool Schemas for Claude
# =============================================================================


SENTRY_TOOLS = [
    {
        "name": "sentry_get_issue",
        "description": "Get detailed information about a Sentry issue including title, culprit, status, event count, and metadata. Use this to understand what an error is about.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "The Sentry issue ID (numeric string)",
                },
            },
            "required": ["issue_id"],
        },
    },
    {
        "name": "sentry_get_latest_event",
        "description": "Get the most recent event for a Sentry issue with full stacktrace, including file paths, line numbers, and local variables. Essential for understanding where and why an error occurred.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "The Sentry issue ID (numeric string)",
                },
            },
            "required": ["issue_id"],
        },
    },
    {
        "name": "sentry_get_issue_events",
        "description": "List recent events for a Sentry issue. Useful for seeing patterns across multiple occurrences of the same error.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "The Sentry issue ID (numeric string)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of events to return (default: 10, max: 100)",
                    "default": 10,
                },
            },
            "required": ["issue_id"],
        },
    },
    {
        "name": "sentry_list_project_issues",
        "description": "List recent issues for a Sentry project. Can filter by search query using Sentry's search syntax (e.g., 'is:unresolved level:error').",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_slug": {
                    "type": "string",
                    "description": "The Sentry project slug (e.g., 'my-python-app')",
                },
                "query": {
                    "type": "string",
                    "description": "Optional search query using Sentry syntax (e.g., 'is:unresolved', 'level:error')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of issues to return (default: 25, max: 100)",
                    "default": 25,
                },
            },
            "required": ["project_slug"],
        },
    },
]
