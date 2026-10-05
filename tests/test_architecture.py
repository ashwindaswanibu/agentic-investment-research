from pathlib import Path

from researchdesk.architecture import render_architecture


def test_agent_prompt_and_tool_map_matches_executable_registry():
    root = Path(__file__).resolve().parents[1]
    assert (root / "docs/generated/agent-architecture.md").read_text() == render_architecture()
