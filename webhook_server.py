"""
FastAPI webhook server for receiving Sentry webhooks.

Handles incoming webhooks from Sentry, validates signatures,
and triggers the SRE agent to investigate issues.
"""

import asyncio
import json
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from harness import get_tools_for_context, run_agent_loop
from repo_context import RepoContext, create_repo_context
from sentry_context import SentryContext, create_sentry_context
from sentry_tools import (
    parse_event_alert_webhook,
    parse_issue_webhook,
    verify_webhook_signature,
)

# Create router for webhook endpoints
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def get_sentry_context_from_env() -> Optional[SentryContext]:
    """
    Create SentryContext from environment variables.

    Required env vars:
        SENTRY_AUTH_TOKEN: API token from Sentry Internal Integration
        SENTRY_ORG_SLUG: Organization slug

    Optional env vars:
        SENTRY_BASE_URL: API base URL (default: https://sentry.io/api/0)
        SENTRY_WEBHOOK_SECRET: Secret for validating webhooks

    Returns:
        SentryContext if env vars are set, None otherwise
    """
    auth_token = os.environ.get("SENTRY_AUTH_TOKEN")
    org_slug = os.environ.get("SENTRY_ORG_SLUG")

    if not auth_token or not org_slug:
        return None

    return create_sentry_context(
        auth_token=auth_token,
        organization_slug=org_slug,
        base_url=os.environ.get("SENTRY_BASE_URL", "https://sentry.io/api/0"),
        webhook_secret=os.environ.get("SENTRY_WEBHOOK_SECRET"),
    )


def get_repo_context_from_env() -> Optional[RepoContext]:
    """
    Create RepoContext from environment variables.

    Required env vars:
        REPO_PATH: Path to the local git repository

    Optional env vars:
        ALLOW_PUSH_TO_MAIN: Whether to allow pushing to main/master (default: false)
        REQUIRE_PUSH_CONFIRMATION: Whether to require push confirmation (default: true)

    Returns:
        RepoContext if env vars are set, None otherwise
    """
    repo_path = os.environ.get("REPO_PATH")

    if not repo_path:
        return None

    return create_repo_context(
        repo_path=repo_path,
        allow_push_to_main=os.environ.get("ALLOW_PUSH_TO_MAIN", "").lower() == "true",
        require_push_confirmation=False,
    )


async def run_agent_for_sentry_issue(
    webhook_payload: dict,
    sentry_ctx: SentryContext,
    repo_ctx: Optional[RepoContext],
) -> None:
    """
    Run the agent loop to investigate a Sentry issue.

    This is run as a background task after webhook is received.

    Args:
        webhook_payload: The complete webhook JSON payload from Sentry
        sentry_ctx: Sentry context for API calls
        repo_ctx: Optional repo context for file operations
    """
    # Convert the payload to a formatted JSON string for the prompt
    payload_json = json.dumps(webhook_payload, indent=2, default=str)

    # Build the investigation prompt with the full webhook payload
    prompt = f"""A new Sentry alert has been triggered. Here is the complete webhook payload:

```json
{payload_json}
```

Please investigate this error:
1. Analyze the webhook payload to understand:
   - What the error/issue is (check message, title, level)
   - The stacktrace (frames with file paths, line numbers, function names, context)
   - User and request context if available
   - Environment, tags, and any extra data
2. If needed, use sentry_get_issue or sentry_get_latest_event for additional details
3. If a local repository is available, read the relevant source files to understand the context
4. Provide a summary of:
   - What the error is
   - Where it occurred (file, function, line)
   - Why it might be happening
   - The impact (user affected, environment, frequency)
   - Suggested fix if applicable
"""

    # Get tools based on what context is available
    tools = get_tools_for_context(
        include_example=False,
        include_local_repo=repo_ctx is not None,
        include_sentry=True,
    )

    # Extract issue_id for logging purposes
    issue_id = webhook_payload.get("data", {}).get("event", {}).get("issue_id", "unknown")

    # Run the agent loop (this is blocking, but we're in a background task)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_agent_loop(
                user_prompt=prompt,
                tools=tools,
                repo_context=repo_ctx,
                sentry_context=sentry_ctx,
            ),
        )
        print(f"\n{'='*50}")
        print(f"Agent investigation complete for issue {issue_id}")
        print(f"{'='*50}")
        print(result)
    except Exception as e:
        print(f"Error running agent for issue {issue_id}: {e}")


@router.post("/sentry")
async def handle_sentry_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    sentry_hook_resource: Optional[str] = Header(None, alias="Sentry-Hook-Resource"),
    sentry_hook_signature: Optional[str] = Header(None, alias="Sentry-Hook-Signature"),
) -> dict:
    """
    Handle incoming Sentry webhooks.

    Validates the webhook signature (if secret is configured),
    parses the payload, and triggers the agent to investigate.

    Headers:
        Sentry-Hook-Resource: Type of webhook (issue, event_alert, etc.)
        Sentry-Hook-Signature: HMAC signature for validation

    Returns:
        JSON response confirming receipt
    """
    # Get raw body for signature verification
    body = await request.body()

    # Get contexts from environment
    sentry_ctx = get_sentry_context_from_env()
    if sentry_ctx is None:
        raise HTTPException(
            status_code=500,
            detail="Sentry not configured. Set SENTRY_AUTH_TOKEN and SENTRY_ORG_SLUG.",
        )

    # Verify signature if secret is configured
    if sentry_ctx.webhook_secret:
        if not sentry_hook_signature:
            raise HTTPException(status_code=401, detail="Missing webhook signature")

        if not verify_webhook_signature(body, sentry_hook_signature, sentry_ctx.webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse the payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Get repo context if available
    repo_ctx = get_repo_context_from_env()

    # Handle different webhook types
    if sentry_hook_resource == "issue":
        # Issue webhooks (issue.created, issue.resolved, etc.)
        parsed = parse_issue_webhook(payload)
        action = payload.get("action", "")

        # Only trigger agent for new issues
        if action == "created" and parsed["issue_id"]:
            background_tasks.add_task(
                run_agent_for_sentry_issue,
                webhook_payload=payload,
                sentry_ctx=sentry_ctx,
                repo_ctx=repo_ctx,
            )

            return {
                "status": "accepted",
                "message": f"Agent triggered for issue {parsed['issue_id']}",
                "issue_id": parsed["issue_id"],
            }

        return {
            "status": "ignored",
            "message": f"Issue action '{action}' does not trigger agent",
        }

    elif sentry_hook_resource == "event_alert":
        # Event alert webhooks (alert rules)
        parsed = parse_event_alert_webhook(payload)
        issue_id = parsed.get("issue_id", "")

        # Trigger agent with the full payload
        background_tasks.add_task(
            run_agent_for_sentry_issue,
            webhook_payload=payload,
            sentry_ctx=sentry_ctx,
            repo_ctx=repo_ctx,
        )

        return {
            "status": "accepted",
            "message": f"Agent triggered for alert on issue {issue_id}" if issue_id else "Agent triggered for alert",
            "issue_id": issue_id,
        }

    else:
        # Unknown or unsupported webhook type
        return {
            "status": "ignored",
            "message": f"Webhook resource '{sentry_hook_resource}' not handled",
        }


@router.get("/sentry/health")
async def sentry_webhook_health() -> dict:
    """
    Health check endpoint for Sentry webhook configuration.

    Returns configuration status without exposing secrets.
    """
    sentry_ctx = get_sentry_context_from_env()
    repo_ctx = get_repo_context_from_env()

    return {
        "status": "ok",
        "sentry_configured": sentry_ctx is not None,
        "sentry_org": sentry_ctx.organization_slug if sentry_ctx else None,
        "webhook_secret_configured": sentry_ctx.webhook_secret is not None if sentry_ctx else False,
        "repo_configured": repo_ctx is not None,
        "repo_path": str(repo_ctx.repo_path) if repo_ctx else None,
    }
