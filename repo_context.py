"""
Repository context management for local repository operations.

Provides path validation, security checks, and configuration for
local file and git operations.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import subprocess


class RepoContextError(Exception):
    """Exception raised for repository context errors."""

    pass


@dataclass
class RepoContext:
    """
    Context for local repository operations.

    Provides path resolution with security checks and configuration
    for git operations.
    """

    repo_path: Path
    allow_push_to_main: bool = False
    require_push_confirmation: bool = True
    remote_name: str = "origin"
    _validated: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        """Validate and normalize the repository path."""
        if isinstance(self.repo_path, str):
            self.repo_path = Path(self.repo_path)

        self.repo_path = self.repo_path.resolve()

        if not self.repo_path.exists():
            raise RepoContextError(f"Repository path does not exist: {self.repo_path}")

        if not self.repo_path.is_dir():
            raise RepoContextError(
                f"Repository path is not a directory: {self.repo_path}"
            )

        if not self._is_git_repo():
            raise RepoContextError(
                f"Repository path is not a git repository: {self.repo_path}"
            )

        self._validated = True

    def _is_git_repo(self) -> bool:
        """Check if the path is a valid git repository."""
        git_dir = self.repo_path / ".git"
        if git_dir.exists() and git_dir.is_dir():
            return True

        # Check if it's inside a git worktree or bare repo
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def resolve_path(self, relative_path: str) -> Path:
        """
        Resolve a relative path within the repository.

        Prevents path traversal attacks by ensuring the resolved path
        is within the repository root.

        Args:
            relative_path: Path relative to the repository root

        Returns:
            Absolute path within the repository

        Raises:
            RepoContextError: If the path would escape the repository
        """
        # Normalize and resolve the path
        normalized = Path(relative_path)

        # Remove any leading slashes to treat as relative
        if normalized.is_absolute():
            # Convert absolute path to relative by removing root
            try:
                normalized = normalized.relative_to("/")
            except ValueError:
                # Windows absolute path or other format
                normalized = Path(str(normalized).lstrip("/\\"))

        resolved = (self.repo_path / normalized).resolve()

        # Security check: ensure path is within repo
        try:
            resolved.relative_to(self.repo_path)
        except ValueError:
            raise RepoContextError(
                f"Path traversal attempt detected: '{relative_path}' "
                f"resolves outside repository"
            )

        return resolved

    def get_relative_path(self, absolute_path: Path) -> str:
        """
        Get the relative path from the repository root.

        Args:
            absolute_path: Absolute path to convert

        Returns:
            Relative path string from repository root
        """
        return str(absolute_path.relative_to(self.repo_path))

    def get_current_branch(self) -> Optional[str]:
        """Get the current git branch name."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def get_remote_url(self) -> Optional[str]:
        """Get the remote URL for the configured remote."""
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", self.remote_name],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def is_protected_branch(self, branch: Optional[str] = None) -> bool:
        """
        Check if a branch is protected (main/master).

        Args:
            branch: Branch name to check, defaults to current branch

        Returns:
            True if the branch is main or master
        """
        branch = branch or self.get_current_branch()
        if branch is None:
            return True  # Conservative: treat unknown as protected
        return branch.lower() in ("main", "master")

    def to_dict(self) -> dict:
        """Convert context to dictionary for serialization."""
        return {
            "repo_path": str(self.repo_path),
            "allow_push_to_main": self.allow_push_to_main,
            "require_push_confirmation": self.require_push_confirmation,
            "remote_name": self.remote_name,
            "current_branch": self.get_current_branch(),
            "remote_url": self.get_remote_url(),
        }


def create_repo_context(
    repo_path: str | Path,
    allow_push_to_main: bool = False,
    require_push_confirmation: bool = True,
    remote_name: str = "origin",
) -> RepoContext:
    """
    Factory function to create a RepoContext with validation.

    Args:
        repo_path: Path to the local git repository
        allow_push_to_main: Whether to allow pushing to main/master branches
        require_push_confirmation: Whether to require confirmed=True for push
        remote_name: Name of the remote to use for push operations

    Returns:
        Validated RepoContext instance

    Raises:
        RepoContextError: If validation fails
    """
    return RepoContext(
        repo_path=Path(repo_path),
        allow_push_to_main=allow_push_to_main,
        require_push_confirmation=require_push_confirmation,
        remote_name=remote_name,
    )
