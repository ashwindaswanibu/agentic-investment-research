"""Retain delayed options evidence for a research case, without execution authority.

Agents and the local operator CLI use this same acquisition path. Tool retries
recover committed artifacts through the existing registry; explicit new calls
capture new observations rather than rewriting earlier receipt timestamps.
"""

from datetime import date
from functools import partial

from pydantic import Field

from researchdesk.data.options import TradierOptionsProvider
from researchdesk.domain import ALL_ROLES, Input, artifact_ref, compact_artifact
from researchdesk.errors import DomainError


class OptionsExpirationsInput(Input):
    underlying: str = Field(pattern=r"^[A-Z][A-Z0-9./\-]{0,14}$")
    purpose: str = Field(min_length=10, max_length=1000, pattern=r"\S")
    source_artifact_ids: list[str] = Field(default_factory=list, max_length=10)


class OptionsChainInput(OptionsExpirationsInput):
    expiration: date


def options_provider(settings):
    return TradierOptionsProvider(settings.tradier_sandbox_token)


def acquire_options(research, args, *, case_id, context=None, provider=None):
    """One bounded fetch, then one immutable commit; no I/O inside a transaction."""
    if research.settings.read_only:
        raise DomainError("READ_ONLY", "Read-only deployments cannot acquire options data.", 403)
    case = research.store.get_case(case_id)
    if case["status"] == "cancelled":
        raise DomainError("CANCELLED", "This investigation has been cancelled.", 409)
    if context:
        context.check_cancelled()
        if context.case_id != case_id:
            raise DomainError("ARTIFACT_CASE", "Acquisition belongs to the current case.")
    inputs = [
        artifact_ref(research.artifact(identifier, case_id=case_id))
        for identifier in dict.fromkeys(args.source_artifact_ids)
    ]
    provider = provider or options_provider(research.settings)
    chain = isinstance(args, OptionsChainInput)
    kind = "options_chain" if chain else "options_expirations"
    result = (
        provider.chain(args.underlying, args.expiration)
        if chain
        else provider.expirations(args.underlying)
    )
    content = {**result, "research_purpose": args.purpose}
    metadata = {
        "inputs": inputs,
        "request": args.model_dump(mode="json"),
        "source": "Tradier sandbox",
        "research_only": True,
        "execution_eligible": False,
        "untrusted_source": True,
        "synthetic": content.get("synthetic", False),
    }
    title = (
        f"Options chain · {args.underlying} · {args.expiration}"
        if chain
        else f"Options expirations · {args.underlying}"
    )
    if context:
        return research.save(context, kind, title, content, metadata, require_active_case=True)
    # Operator output has no fabricated agent/task attribution. Every explicit
    # invocation is a new observation; agent retries use registry recovery.
    return research.store.put_artifact(
        case_id, None, kind, title, content, metadata, require_active_case=True
    )


def _tool(research, context, args):
    return compact_artifact(
        acquire_options(research, args, case_id=context.case_id, context=context)
    )


def register_options_tools(registry, research):
    registry.register(
        "discover_options_expirations",
        "Discover available expirations for a US underlying through Tradier sandbox and "
        "retain the observation in this investigation. State the research purpose and "
        "optionally link hypothesis/evidence IDs from this case. Expiry availability is "
        "not proof of quote liquidity or suitability. Returns a compact saved-artifact "
        "receipt; inspect full dates with read_artifact or inspect_source.",
        OptionsExpirationsInput,
        ALL_ROLES,
        partial(_tool, research),
        side_effect="artifact",
    )
    registry.register(
        "acquire_options_chain",
        "Retain one underlying/expiration chain from Tradier's 15-minute-delayed sandbox "
        "for a stated research purpose. Choose expiry from the research horizon, not "
        "automatically the nearest date. Optional source_artifact_ids link the case's "
        "hypothesis/evidence. Bid/ask market times and receipt time remain distinct; "
        "missing values and validation issues are explicit. Research evidence only: "
        "cannot authorize an order or backtest fill, and delayed prices cannot fill "
        "a newer decision. Returns a compact receipt; inspect contract rows using "
        "inspect_source at /contracts or read_artifact. A refresh is a new artifact.",
        OptionsChainInput,
        ALL_ROLES,
        partial(_tool, research),
        side_effect="artifact",
    )
