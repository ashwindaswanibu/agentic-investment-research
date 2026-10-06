"""Generate the agent/tool/prompt map from the actual registry and prompt source.

No database, model, network or sandbox process is opened. --check is the drift
check used by tests; the checked-in document is a readable repository artifact.
"""

import argparse
import ast
import hashlib
import inspect
import textwrap
from pathlib import Path

from researchdesk.agents import providers, runtime, specialists
from researchdesk.config import Settings
from researchdesk.domain import ResearchTools


def _assignment(function, name, value_type=None):
    source = textwrap.dedent(inspect.getsource(function))
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            if value_type is None or isinstance(node.value, value_type):
                return ast.get_source_segment(source, node)
    raise ValueError(f"Prompt assembly {name} was moved; update the architecture exporter.")


def render_architecture():
    registry = runtime.register_delegation(ResearchTools(None, Settings(_env_file=None)).registry())
    tools = sorted(registry.describe(), key=lambda item: item["name"])
    sections = [
        "# Agent, prompt and tool architecture\n",
        "Generated from the executable registry and prompt assembly. Regenerate with "
        "`python -m researchdesk.architecture`; `--check` fails on drift. This is the "
        "implemented architecture, not a claim that a live model run or profitable "
        "strategy has been demonstrated.\n",
        "## Runtime and prompt composition\n",
        "```mermaid\nflowchart TD\n"
        ' Case["Saved case question"] --> Task["Persisted task instruction and inputs"]\n'
        ' Shared["Shared SYSTEM prompt + stored role"] --> Prompt["Assembled model request"]\n'
        " Task --> Prompt\n"
        ' Profile["Reviewed specialist instructions + spec hash"] --> Prompt\n'
        ' ToolSchemas["Allowed tool descriptions + JSON schemas"] --> Prompt\n'
        ' Transcript["Persisted messages and delegated outcomes"] --> Prompt\n'
        ' Prompt --> Provider["OpenAI Responses or Claude CLI adapter"]\n'
        ' Provider --> Calls["Persist proposed tool calls"]\n'
        ' Calls --> Gate["Schema, role, profile, budget and lease checks"]\n'
        ' Gate --> Handler["Registered application handler"]\n'
        ' Handler --> Record["Immutable artifacts + tool results + events"]\n'
        " Record --> Transcript\n"
        ' Handler --> Delegate["Coordinator delegates bounded child task"]\n'
        " Delegate --> Task\n"
        ' Handler --> Experiment["Causal simulation and automatic assessment"]\n'
        " Experiment --> Record\n"
        ' Handler --> Forecast["Immutable forecast before event window"]\n'
        " Forecast --> Record\n"
        ' Operator["Write-authorized operator after event window"] --> '
        'Resolution["Source-cited outcome and correction history"]\n'
        " Forecast --> Resolution\n"
        " Resolution --> Record\n"
        ' Resolution --> Score["Per-record Brier loss against saved baseline"]\n```\n',
        "There are four base roles. They share the system prompt; this is not four "
        "separate domain experts. A reviewed specialist activation augments a researcher "
        "with stored domain instructions and narrows its tool permissions. Only the "
        "coordinator delegates. A coder implements tools/strategies; a separate reviewer "
        "reviews exact immutable versions. Dynamic instruction text lives in the task "
        "and specialist artifacts, not a hard-coded list in this document.\n",
        "## Complete tool permissions\n",
        "Every registered tool appears below. These are maximum role permissions; a "
        "specialist profile can narrow them. Registration does not establish provider "
        "readiness, source access, research quality or permission to trade.\n",
    ]
    for role in ("coordinator", "researcher", "coder", "reviewer"):
        lines = [f"### {role.title()}\n", "```mermaid\nflowchart LR", f' role["{role}"]']
        for tool in tools:
            if role in tool["roles"]:
                name = tool["name"]
                lines.append(f' role --> tool_{name}["{name}"]')
        lines.append("```\n")
        sections.append("\n".join(lines))
    sections.append("| Tool | Effect | Description |\n|---|---|---|")
    for tool in tools:
        description = tool["description"].replace("|", "\\|").replace("\n", " ")
        sections.append(f"| `{tool['name']}` | {tool['side_effect']} | {description} |")
    sections.extend(
        [
            "\n## Exact shared prompt\n",
            "Source: [runtime.py](../../src/researchdesk/agents/runtime.py). The runtime "
            "adds the stored role and verified specialist instructions.\n",
            f"```text\n{runtime.SYSTEM.strip()}\n```\n",
            "## Initial task message\n",
            "The case, instruction and input IDs are inserted from persisted records. "
            "Tool outputs and child outcomes then extend the durable transcript.\n",
            "```python\n" + _assignment(runtime.Runtime.run_task, "messages", ast.List) + "\n```\n",
            "## Specialist prompt and permission assembly\n",
            "Source: [specialists.py](../../src/researchdesk/agents/specialists.py). "
            "The activation and independent review must bind the exact specification hash.\n",
            "```python\n" + _assignment(specialists._task_policy, "instructions") + "\n```\n",
            "## Provider-specific prompt assembly\n",
            "OpenAI receives the assembled instruction plus native function schemas. "
            "Claude receives the following additional protocol text and serialized "
            "conversation; its host tools are disabled. Source: "
            "[providers.py](../../src/researchdesk/agents/providers.py).\n",
            "```python\n"
            + _assignment(providers.ClaudeCLIProvider.complete, "system")
            + "\n\n"
            + _assignment(providers.ClaudeCLIProvider.complete, "prompt")
            + "\n```\n",
            "## Experiment assessment path\n",
            "```mermaid\nflowchart LR\n"
            ' Run["run_experiment"] --> Sim["Backtest / generated policy / SMA walk-forward"]\n'
            ' Sim --> Assessment["Deterministic return, baseline, exposure and evidence checks"]\n'
            ' Assessment --> Commit["One immutable experiment: result + assessment + digest"]\n'
            ' Commit --> Agent["Compact tool response includes assessment"]\n'
            ' Commit --> UI["Experiment inspector"]\n'
            ' Old["assess-strategy CLI + original experiment ID"] --> '
            'Version["Versioned annotation; original preserved"]\n'
            " Version --> UI\n```\n",
            "The assessment cannot activate trading or certify alpha. Existing review, "
            "paper mandate and ledger gates remain distinct. Continuous strategy research "
            "monitoring, options execution and automatic refinement are not represented "
            "as implemented nodes.\n",
            "## Source versions\n",
            "SHA-256 values bind this map to its prompt/registry implementation. The "
            "drift test regenerates descriptions, role edges and prompt text.\n",
        ]
    )
    package = Path(__file__).resolve().parent
    for relative in (
        "agents/runtime.py",
        "agents/providers.py",
        "agents/specialists.py",
        "domain.py",
    ):
        digest = hashlib.sha256((package / relative).read_bytes()).hexdigest()
        sections.append(f"- `{relative}`: `{digest}`")
    return "\n".join(sections) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/generated/agent-architecture.md"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render_architecture()
    if args.check:
        if not args.output.exists() or args.output.read_text() != rendered:
            raise SystemExit("Agent architecture is stale; regenerate it from the codebase.")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
