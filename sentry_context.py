"""
Sentry context management for Sentry API operations.

Provides authentication, configuration, and API helpers for
interacting with Sentry's API and webhooks.
"""

from dataclasses import dataclass
from typing import Optional


class SentryContextError(Exception):
    """Exception raised for Sentry context errors."""

    pass


@dataclass
class SentryContext:
    """
    Context for Sentry API operations.

    Provides authentication and configuration for making Sentry API calls
    and validating incoming webhooks.
    """

    auth_token: str
    organization_slug: str
    base_url: str = "https://sentry.io/api/0"
    webhook_secret: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate required fields."""
        if not self.auth_token:
            raise SentryContextError("auth_token is required")
        if not self.organization_slug:
            raise SentryContextError("organization_slug is required")

        # Normalize base_url (remove trailing slash)
        self.base_url = self.base_url.rstrip("/")

    def get_headers(self) -> dict[str, str]:
        """
        Get HTTP headers for Sentry API requests.

        Returns:
            Dictionary of headers including authorization
        """
        return {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
        }

    def get_issue_url(self, issue_id: str) -> str:
        """
        Get the API URL for an issue.

        Args:
            issue_id: Sentry issue ID

        Returns:
            Full API URL for the issue
        """
        return f"{self.base_url}/issues/{issue_id}/"

    def get_issue_events_url(self, issue_id: str) -> str:
        """
        Get the API URL for an issue's events.

        Args:
            issue_id: Sentry issue ID

        Returns:
            Full API URL for the issue's events
        """
        return f"{self.base_url}/issues/{issue_id}/events/"

    def get_latest_event_url(self, issue_id: str) -> str:
        """
        Get the API URL for an issue's latest event.

        Args:
            issue_id: Sentry issue ID

        Returns:
            Full API URL for the latest event
        """
        return f"{self.base_url}/issues/{issue_id}/events/latest/"

    def get_project_issues_url(self, project_slug: str) -> str:
        """
        Get the API URL for a project's issues.

        Args:
            project_slug: Sentry project slug

        Returns:
            Full API URL for the project's issues
        """
        return f"{self.base_url}/projects/{self.organization_slug}/{project_slug}/issues/"

    def to_dict(self) -> dict:
        """Convert context to dictionary for serialization."""
        return {
            "organization_slug": self.organization_slug,
            "base_url": self.base_url,
            "has_webhook_secret": self.webhook_secret is not None,
        }


def create_sentry_context(
    auth_token: str,
    organization_slug: str,
    base_url: str = "https://sentry.io/api/0",
    webhook_secret: Optional[str] = None,
) -> SentryContext:
    """
    Factory function to create a SentryContext with validation.

    Args:
        auth_token: Sentry API token (from Internal Integration)
        organization_slug: Organization slug (e.g., "my-org")
        base_url: Sentry API base URL (default: https://sentry.io/api/0)
        webhook_secret: Secret for validating incoming webhooks

    Returns:
        Validated SentryContext instance

    Raises:
        SentryContextError: If validation fails
    """
    return SentryContext(
        auth_token=auth_token,
        organization_slug=organization_slug,
        base_url=base_url,
        webhook_secret=webhook_secret,
    )
