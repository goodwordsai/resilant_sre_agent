"""
Local repository tools for file operations and git commands.

Provides tools for reading, writing, and editing files in a local repository,
as well as git operations like status, add, commit, push, diff, and log.
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from repo_context import RepoContext, RepoContextError


# Constants
MAX_FILE_SIZE = 1024 * 1024  # 1MB limit for file reads
DEFAULT_ENCODING = "utf-8"


# =============================================================================
# File Operations
# =============================================================================


def local_read_file(ctx: RepoContext, path: str) -> str:
    """
    Read file contents from the repository.

    Args:
        ctx: Repository context
        path: Relative path to the file

    Returns:
        JSON with file content or error message
    """
    try:
        resolved_path = ctx.resolve_path(path)

        if not resolved_path.exists():
            return json.dumps({"error": f"File not found: {path}"})

        if not resolved_path.is_file():
            return json.dumps({"error": f"Path is not a file: {path}"})

        file_size = resolved_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            return json.dumps({
                "error": f"File too large: {file_size} bytes (max {MAX_FILE_SIZE})"
            })

        content = resolved_path.read_text(encoding=DEFAULT_ENCODING)

        return json.dumps({
            "path": path,
            "content": content,
            "size": file_size,
        })

    except RepoContextError as e:
        return json.dumps({"error": str(e)})
    except UnicodeDecodeError:
        return json.dumps({"error": f"File is not valid UTF-8: {path}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to read file: {e}"})


def local_write_file(ctx: RepoContext, path: str, content: str) -> str:
    """
    Write or create a file in the repository.

    Creates parent directories if they don't exist.

    Args:
        ctx: Repository context
        path: Relative path to the file
        content: Content to write

    Returns:
        JSON with result or error message
    """
    try:
        resolved_path = ctx.resolve_path(path)

        # Create parent directories if needed
        resolved_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if file exists (for reporting created vs updated)
        existed = resolved_path.exists()

        resolved_path.write_text(content, encoding=DEFAULT_ENCODING)

        return json.dumps({
            "path": path,
            "action": "updated" if existed else "created",
            "size": len(content.encode(DEFAULT_ENCODING)),
        })

    except RepoContextError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Failed to write file: {e}"})


def local_edit_file(
    ctx: RepoContext,
    path: str,
    old_content: str,
    new_content: str,
) -> str:
    """
    Edit a file by replacing specific content.

    The old_content must match exactly once in the file for the
    replacement to succeed.

    Args:
        ctx: Repository context
        path: Relative path to the file
        old_content: Content to find and replace (must be unique)
        new_content: Replacement content

    Returns:
        JSON with result or error message
    """
    try:
        resolved_path = ctx.resolve_path(path)

        if not resolved_path.exists():
            return json.dumps({"error": f"File not found: {path}"})

        if not resolved_path.is_file():
            return json.dumps({"error": f"Path is not a file: {path}"})

        current_content = resolved_path.read_text(encoding=DEFAULT_ENCODING)

        # Count occurrences
        count = current_content.count(old_content)

        if count == 0:
            return json.dumps({
                "error": "old_content not found in file",
                "path": path,
            })

        if count > 1:
            return json.dumps({
                "error": f"old_content found {count} times, must be unique",
                "path": path,
            })

        # Perform the replacement
        new_file_content = current_content.replace(old_content, new_content, 1)
        resolved_path.write_text(new_file_content, encoding=DEFAULT_ENCODING)

        return json.dumps({
            "path": path,
            "action": "edited",
            "old_length": len(old_content),
            "new_length": len(new_content),
        })

    except RepoContextError as e:
        return json.dumps({"error": str(e)})
    except UnicodeDecodeError:
        return json.dumps({"error": f"File is not valid UTF-8: {path}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to edit file: {e}"})


def local_list_directory(
    ctx: RepoContext,
    path: str = ".",
    include_hidden: bool = False,
) -> str:
    """
    List contents of a directory in the repository.

    Args:
        ctx: Repository context
        path: Relative path to the directory (default: repo root)
        include_hidden: Whether to include hidden files (starting with .)

    Returns:
        JSON with directory contents or error message
    """
    try:
        resolved_path = ctx.resolve_path(path)

        if not resolved_path.exists():
            return json.dumps({"error": f"Directory not found: {path}"})

        if not resolved_path.is_dir():
            return json.dumps({"error": f"Path is not a directory: {path}"})

        entries = []
        for entry in sorted(resolved_path.iterdir()):
            name = entry.name

            # Skip hidden files unless requested
            if not include_hidden and name.startswith("."):
                continue

            entry_info = {
                "name": name,
                "type": "directory" if entry.is_dir() else "file",
            }

            if entry.is_file():
                entry_info["size"] = entry.stat().st_size

            entries.append(entry_info)

        return json.dumps({
            "path": path,
            "entries": entries,
            "count": len(entries),
        })

    except RepoContextError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Failed to list directory: {e}"})


def local_file_info(ctx: RepoContext, path: str) -> str:
    """
    Get metadata about a file or directory.

    Args:
        ctx: Repository context
        path: Relative path to the file or directory

    Returns:
        JSON with file metadata or error message
    """
    try:
        resolved_path = ctx.resolve_path(path)

        if not resolved_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        stat_info = resolved_path.stat()

        info = {
            "path": path,
            "type": "directory" if resolved_path.is_dir() else "file",
            "size": stat_info.st_size,
            "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
            "created": datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
        }

        if resolved_path.is_file():
            info["extension"] = resolved_path.suffix or None

        return json.dumps(info)

    except RepoContextError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Failed to get file info: {e}"})


# =============================================================================
# Git Operations
# =============================================================================


def _run_git_command(
    ctx: RepoContext,
    args: list[str],
    timeout: int = 30,
) -> tuple[int, str, str]:
    """
    Run a git command in the repository.

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=ctx.repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", "git command not found"


def git_status(ctx: RepoContext) -> str:
    """
    Get the current git status.

    Returns staged, unstaged, and untracked files along with branch info.

    Args:
        ctx: Repository context

    Returns:
        JSON with git status information
    """
    try:
        # Get current branch
        branch = ctx.get_current_branch()

        # Get porcelain status for parsing
        returncode, stdout, stderr = _run_git_command(
            ctx, ["status", "--porcelain", "-b"]
        )

        if returncode != 0:
            return json.dumps({"error": f"git status failed: {stderr}"})

        lines = stdout.strip().split("\n") if stdout.strip() else []

        staged = []
        unstaged = []
        untracked = []

        for line in lines:
            if line.startswith("##"):
                continue  # Branch info line

            if len(line) < 3:
                continue

            index_status = line[0]
            worktree_status = line[1]
            filepath = line[3:]

            # Handle renames (show both old and new)
            if " -> " in filepath:
                filepath = filepath.split(" -> ")[1]

            if index_status == "?":
                untracked.append(filepath)
            elif index_status != " ":
                staged.append({"status": index_status, "path": filepath})

            if worktree_status not in (" ", "?"):
                unstaged.append({"status": worktree_status, "path": filepath})

        return json.dumps({
            "branch": branch,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to get git status: {e}"})


def git_add(ctx: RepoContext, paths: list[str]) -> str:
    """
    Stage files for commit.

    Args:
        ctx: Repository context
        paths: List of file paths to stage (relative to repo root)

    Returns:
        JSON with result or error message
    """
    try:
        if not paths:
            return json.dumps({"error": "No paths provided"})

        # Validate all paths are within repo
        for path in paths:
            ctx.resolve_path(path)

        returncode, stdout, stderr = _run_git_command(ctx, ["add"] + paths)

        if returncode != 0:
            return json.dumps({"error": f"git add failed: {stderr}"})

        return json.dumps({
            "action": "staged",
            "paths": paths,
        })

    except RepoContextError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Failed to stage files: {e}"})


def git_commit(ctx: RepoContext, message: str) -> str:
    """
    Create a commit with the staged changes.

    Args:
        ctx: Repository context
        message: Commit message

    Returns:
        JSON with commit info or error message
    """
    try:
        if not message or not message.strip():
            return json.dumps({"error": "Commit message cannot be empty"})

        returncode, stdout, stderr = _run_git_command(
            ctx, ["commit", "-m", message]
        )

        if returncode != 0:
            if "nothing to commit" in stderr or "nothing to commit" in stdout:
                return json.dumps({"error": "Nothing to commit"})
            return json.dumps({"error": f"git commit failed: {stderr}"})

        # Get the commit hash
        returncode, stdout, stderr = _run_git_command(
            ctx, ["rev-parse", "HEAD"]
        )

        commit_hash = stdout.strip() if returncode == 0 else "unknown"

        return json.dumps({
            "action": "committed",
            "message": message,
            "sha": commit_hash,
            "branch": ctx.get_current_branch(),
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to commit: {e}"})


def git_push(
    ctx: RepoContext,
    branch: Optional[str] = None,
    confirmed: bool = False,
) -> str:
    """
    Push commits to the remote repository.

    Safety guards:
    1. Blocks push to main/master if allow_push_to_main=False
    2. Requires confirmed=True if require_push_confirmation=True
    3. Returns warning message for protected branches

    Args:
        ctx: Repository context
        branch: Branch to push (default: current branch)
        confirmed: Must be True to confirm the push operation

    Returns:
        JSON with result or error/warning message
    """
    try:
        target_branch = branch or ctx.get_current_branch()

        if target_branch is None:
            return json.dumps({"error": "Could not determine target branch"})

        # Safety layer 1: Check if pushing to protected branch is allowed
        if ctx.is_protected_branch(target_branch):
            if not ctx.allow_push_to_main:
                return json.dumps({
                    "error": f"Push to '{target_branch}' is blocked. "
                    "Set allow_push_to_main=True in RepoContext to allow.",
                    "branch": target_branch,
                    "blocked": True,
                })

            # Safety layer 3: Warning for protected branch
            warning = (
                f"WARNING: You are pushing to protected branch '{target_branch}'. "
                "This action affects the main codebase."
            )
        else:
            warning = None

        # Safety layer 2: Require confirmation
        if ctx.require_push_confirmation and not confirmed:
            return json.dumps({
                "error": "Push requires confirmation. "
                "Call with confirmed=True to proceed.",
                "branch": target_branch,
                "requires_confirmation": True,
                "warning": warning,
            })

        # Execute push
        returncode, stdout, stderr = _run_git_command(
            ctx,
            ["push", ctx.remote_name, target_branch],
            timeout=60,
        )

        if returncode != 0:
            return json.dumps({"error": f"git push failed: {stderr}"})

        result = {
            "action": "pushed",
            "branch": target_branch,
            "remote": ctx.remote_name,
        }

        if warning:
            result["warning"] = warning

        return json.dumps(result)

    except Exception as e:
        return json.dumps({"error": f"Failed to push: {e}"})


def git_diff(ctx: RepoContext, staged: bool = False, path: Optional[str] = None) -> str:
    """
    Show changes in the working directory or staging area.

    Args:
        ctx: Repository context
        staged: If True, show staged changes; otherwise show unstaged
        path: Optional specific file path to diff

    Returns:
        JSON with diff output or error message
    """
    try:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            ctx.resolve_path(path)  # Validate path
            args.append("--")
            args.append(path)

        returncode, stdout, stderr = _run_git_command(ctx, args)

        if returncode != 0:
            return json.dumps({"error": f"git diff failed: {stderr}"})

        return json.dumps({
            "staged": staged,
            "path": path,
            "diff": stdout,
            "has_changes": bool(stdout.strip()),
        })

    except RepoContextError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Failed to get diff: {e}"})


def git_log(ctx: RepoContext, count: int = 10) -> str:
    """
    Get recent commit history.

    Args:
        ctx: Repository context
        count: Number of commits to retrieve (default: 10, max: 50)

    Returns:
        JSON with commit history or error message
    """
    try:
        count = min(max(count, 1), 50)  # Clamp between 1 and 50

        returncode, stdout, stderr = _run_git_command(
            ctx,
            [
                "log",
                f"-{count}",
                "--format=%H|%an|%ae|%at|%s",
            ],
        )

        if returncode != 0:
            return json.dumps({"error": f"git log failed: {stderr}"})

        commits = []
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 4)
            if len(parts) == 5:
                commits.append({
                    "sha": parts[0],
                    "author": parts[1],
                    "email": parts[2],
                    "timestamp": int(parts[3]),
                    "message": parts[4],
                })

        return json.dumps({
            "branch": ctx.get_current_branch(),
            "commits": commits,
            "count": len(commits),
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to get log: {e}"})


# =============================================================================
# Tool Execution Router
# =============================================================================


def execute_local_repo_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    ctx: RepoContext,
) -> str:
    """
    Execute a local repository tool and return its result.

    Args:
        tool_name: Name of the tool to execute
        tool_input: Input parameters for the tool
        ctx: Repository context

    Returns:
        JSON string with result or error
    """
    # File operations
    if tool_name == "local_read_file":
        return local_read_file(ctx, tool_input["path"])

    elif tool_name == "local_write_file":
        return local_write_file(ctx, tool_input["path"], tool_input["content"])

    elif tool_name == "local_edit_file":
        return local_edit_file(
            ctx,
            tool_input["path"],
            tool_input["old_content"],
            tool_input["new_content"],
        )

    elif tool_name == "local_list_directory":
        return local_list_directory(
            ctx,
            tool_input.get("path", "."),
            tool_input.get("include_hidden", False),
        )

    elif tool_name == "local_file_info":
        return local_file_info(ctx, tool_input["path"])

    # Git operations
    elif tool_name == "git_status":
        return git_status(ctx)

    elif tool_name == "git_add":
        return git_add(ctx, tool_input["paths"])

    elif tool_name == "git_commit":
        return git_commit(ctx, tool_input["message"])

    elif tool_name == "git_push":
        return git_push(
            ctx,
            tool_input.get("branch"),
            tool_input.get("confirmed", False),
        )

    elif tool_name == "git_diff":
        return git_diff(
            ctx,
            tool_input.get("staged", False),
            tool_input.get("path"),
        )

    elif tool_name == "git_log":
        return git_log(ctx, tool_input.get("count", 10))

    else:
        return json.dumps({"error": f"Unknown local repo tool: {tool_name}"})


# =============================================================================
# Tool Schemas for Claude
# =============================================================================


LOCAL_REPO_TOOLS = [
    # File Operations
    {
        "name": "local_read_file",
        "description": "Read the contents of a file from the local repository. Returns the file content as a string. Limited to 1MB files with UTF-8 encoding.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file within the repository (e.g., 'src/main.py', 'README.md')",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "local_write_file",
        "description": "Write or create a file in the local repository. Creates parent directories if they don't exist. Overwrites the file if it already exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file within the repository",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "local_edit_file",
        "description": "Edit a file by replacing specific content. The old_content must match exactly once in the file for the replacement to succeed. Use this for precise, targeted edits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file within the repository",
                },
                "old_content": {
                    "type": "string",
                    "description": "The exact content to find and replace. Must be unique in the file.",
                },
                "new_content": {
                    "type": "string",
                    "description": "The content to replace old_content with",
                },
            },
            "required": ["path", "old_content", "new_content"],
        },
    },
    {
        "name": "local_list_directory",
        "description": "List the contents of a directory in the repository. Returns files and subdirectories with their types and sizes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the directory (default: repository root)",
                    "default": ".",
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "Whether to include hidden files (starting with .)",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "local_file_info",
        "description": "Get metadata about a file or directory, including size, type, and modification time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file or directory",
                },
            },
            "required": ["path"],
        },
    },
    # Git Operations
    {
        "name": "git_status",
        "description": "Get the current git status including staged files, unstaged changes, untracked files, and current branch.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "git_add",
        "description": "Stage files for commit. Add files to the git staging area.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to stage (relative to repository root)",
                },
            },
            "required": ["paths"],
        },
    },
    {
        "name": "git_commit",
        "description": "Create a commit with the currently staged changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Commit message describing the changes",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "git_push",
        "description": "Push commits to the remote repository. Has safety guards: blocks main/master by default, requires confirmation. Set confirmed=true to proceed with the push.",
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "Branch to push (default: current branch)",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Set to true to confirm the push operation. Required when require_push_confirmation is enabled.",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_diff",
        "description": "Show changes in the working directory or staging area.",
        "input_schema": {
            "type": "object",
            "properties": {
                "staged": {
                    "type": "boolean",
                    "description": "If true, show staged changes; otherwise show unstaged changes",
                    "default": False,
                },
                "path": {
                    "type": "string",
                    "description": "Optional specific file path to diff",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_log",
        "description": "Get recent commit history including SHA, author, timestamp, and message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of commits to retrieve (default: 10, max: 50)",
                    "default": 10,
                },
            },
            "required": [],
        },
    },
]
