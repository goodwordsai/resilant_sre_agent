import anthropic
from typing import Any, Optional

from local_repo_tools import execute_local_repo_tool, LOCAL_REPO_TOOLS
from repo_context import RepoContext
from sentry_context import SentryContext
from sentry_tools import execute_sentry_tool, SENTRY_TOOLS


client = anthropic.Anthropic()


def build_system_prompt(
    repo_context: Optional[RepoContext] = None,
    sentry_context: Optional[SentryContext] = None,
) -> str:
    """
    Build a system prompt that includes repository and Sentry context information.

    Args:
        repo_context: Optional repository context
        sentry_context: Optional Sentry context

    Returns:
        System prompt string
    """
    base_prompt = (
        "You are a helpful AI assistant that can perform various tasks including "
        "calculations, weather lookups, local git repository operations, and "
        "Sentry error investigation."
    )

    sections = []

    if repo_context is not None:
        ctx_info = repo_context.to_dict()
        repo_section = f"""
You have access to a local git repository with the following context:
- Repository path: {ctx_info['repo_path']}
- Current branch: {ctx_info['current_branch'] or 'unknown'}
- Remote URL: {ctx_info['remote_url'] or 'not configured'}
- Push to main/master allowed: {ctx_info['allow_push_to_main']}
- Push confirmation required: {ctx_info['require_push_confirmation']}

When working with files in this repository:
- Use local_* tools for file operations (read, write, edit, list, info)
- Use git_* tools for git operations (status, add, commit, push, diff, log)
- All file paths should be relative to the repository root
- The repository context enforces security boundaries to prevent path traversal
"""
        sections.append(repo_section)

    if sentry_context is not None:
        sentry_info = sentry_context.to_dict()
        sentry_section = f"""
You have access to Sentry for error monitoring and investigation:
- Organization: {sentry_info['organization_slug']}
- API URL: {sentry_info['base_url']}

When investigating Sentry issues:
- Use sentry_get_issue to get issue details (title, status, event count)
- Use sentry_get_latest_event to get the full stacktrace with file paths and line numbers
- Use sentry_get_issue_events to see multiple occurrences of the same error
- Use sentry_list_project_issues to see all recent issues in a project
- When stacktrace includes file paths, use local_read_file to examine the source code
- Correlate Sentry errors with the local codebase to identify root causes
"""
        sections.append(sentry_section)

    if not sections:
        return base_prompt

    return base_prompt + "".join(sections)


def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    repo_context: Optional[RepoContext] = None,
    sentry_context: Optional[SentryContext] = None,
) -> str:
    """
    Execute a tool and return its result.
    Extend this function to add your own tools.
    """
    if tool_name == "calculator":
        try:
            result = eval(tool_input.get("expression", "0"))
            return str(result)
        except Exception as e:
            return f"Error: {e}"
    elif tool_name == "get_weather":
        return f"Weather in {tool_input['location']}: 72°F, sunny"
    elif tool_name.startswith("local_") or tool_name.startswith("git_"):
        if repo_context is None:
            return "Error: Local repository tools require a repo_context. Initialize with create_repo_context()."
        return execute_local_repo_tool(tool_name, tool_input, repo_context)
    elif tool_name.startswith("sentry_"):
        if sentry_context is None:
            return "Error: Sentry tools require a sentry_context. Initialize with create_sentry_context()."
        return execute_sentry_tool(tool_name, tool_input, sentry_context)
    else:
        return f"Tool '{tool_name}' not implemented"


def run_agent_loop(
    user_prompt: str,
    tools: list[dict[str, Any]],
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 4096,
    repo_context: Optional[RepoContext] = None,
    sentry_context: Optional[SentryContext] = None,
) -> str:
    """
    Execute an agent loop that handles:
    - Tool use requests (stop_reason == "tool_use")
    - Tool use responses (tool_result messages)
    - Final text responses (stop_reason == "end_turn")

    Args:
        user_prompt: The user's input prompt
        tools: List of tool definitions
        model: Claude model to use
        max_tokens: Maximum tokens for response
        repo_context: Optional repository context for local file/git operations
        sentry_context: Optional Sentry context for error investigation

    Returns:
        The final text response from Claude.
    """
    messages: list[dict[str, Any]] = []
    messages.append({"role": "user", "content": user_prompt})

    # Build system prompt with repo and sentry context
    system_prompt = build_system_prompt(repo_context, sentry_context)

    while True:
        print(f"\n{'='*50}")
        print("Calling Claude API...")

        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        print(f"Stop reason: {response.stop_reason}")

        if response.stop_reason == "tool_use":
            # Case 1: Tool use request
            print("Response type: TOOL_USE_REQUEST")

            tool_use_blocks = [
                block for block in response.content
                if block.type == "tool_use"
            ]

            for tool_use in tool_use_blocks:
                print(f"  Tool requested: {tool_use.name}")
                print(f"  Tool ID: {tool_use.id}")
                print(f"  Input: {tool_use.input}")

            # Add assistant's response (with tool use blocks) to message history
            messages.append({
                "role": "assistant",
                "content": response.content,
            })

            # Case 2: Tool use response - execute tools and return results
            print("\nResponse type: TOOL_USE_RESPONSE")
            tool_results = []
            for tool_use in tool_use_blocks:
                result = execute_tool(tool_use.name, tool_use.input, repo_context, sentry_context)
                print(f"  Tool: {tool_use.name} -> Result: {result}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                    "is_error": False,
                })

            # Add tool results to message history
            messages.append({
                "role": "user",
                "content": tool_results,
            })

            # Continue loop to get Claude's next response
            continue

        else:
            # Case 3: Final response (end_turn, max_tokens, or stop_sequence)
            print("Response type: FINAL_RESPONSE")

            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text

            print(f"Final text length: {len(final_text)} chars")
            return final_text


def get_tools_for_context(
    include_example: bool = True,
    include_local_repo: bool = False,
    include_sentry: bool = False,
) -> list[dict[str, Any]]:
    """
    Get a list of tools based on the context requirements.

    Args:
        include_example: Include example tools (calculator, weather)
        include_local_repo: Include local repository tools
        include_sentry: Include Sentry error investigation tools

    Returns:
        List of tool definitions
    """
    tools = []

    if include_example:
        tools.extend(EXAMPLE_TOOLS)

    if include_local_repo:
        tools.extend(LOCAL_REPO_TOOLS)

    if include_sentry:
        tools.extend(SENTRY_TOOLS)

    return tools


# Example tools for demonstration
EXAMPLE_TOOLS = [
    {
        "name": "calculator",
        "description": "Perform mathematical calculations. Use this for any math operations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression to evaluate (e.g., '2 + 2', '10 * 5')",
                }
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_weather",
        "description": "Get the current weather for a location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name (e.g., 'San Francisco', 'New York')",
                }
            },
            "required": ["location"],
        },
    },
]


if __name__ == "__main__":
    print("Starting Agent Loop Demo")
    print("=" * 50)

    user_input = "What's 15 + 27? Also, what's the weather in San Francisco?"
    print(f"User: {user_input}")

    # Use get_tools_for_context to build tool list
    tools = get_tools_for_context(include_example=True, include_local_repo=False)
    result = run_agent_loop(user_input, tools)

    print("\n" + "=" * 50)
    print("FINAL RESPONSE:")
    print("=" * 50)
    print(result)
