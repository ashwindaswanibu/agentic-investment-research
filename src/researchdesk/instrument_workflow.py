"""Bind conditional instrument comparisons to immutable research inputs.

This path creates research reports, not orders, historical backtests or forecasts.
Availability checks apply to retained inputs, not the model's prior knowledge.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from functools import partial
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, TypeAdapter

from researchdesk.domain import ALL_ROLES, Input, artifact_ref, compact_artifact
from researchdesk.errors import DomainError
from researchdesk.quant import MarketSnapshot
from researchdesk.quant.instrument_comparison import (
    ComparisonAssumptions,
    InstrumentCandidate,
    compare_instruments,
)


class DatasetStockReference(Input):
    kind: Literal["dataset_close"]
    dataset_id: str = Field(min_length=1, max_length=200)
    session: date
    rationale: str = Field(min_length=20, max_length=2000, pattern=r"\S")
    share_basis_assumption: str = Field(min_length=30, max_length=2000, pattern=r"\S")
    quantity: int | None = Field(default=None, ge=1, le=1_000_000, strict=True)


class AssumedStockReference(Input):
    kind: Literal["assumed_price"]
    price: Decimal = Field(gt=0, le=1_000_000, max_digits=18, decimal_places=8)
    rationale: str = Field(min_length=30, max_length=2000, pattern=r"\S")
    quantity: int | None = Field(default=None, ge=1, le=1_000_000, strict=True)


class InstrumentComparisonInput(Input):
    title: str = Field(min_length=5, max_length=200, pattern=r"\S")
    purpose: str = Field(min_length=20, max_length=2000, pattern=r"\S")
    hypothesis_id: str = Field(min_length=1, max_length=200)
    chain_artifact_id: str = Field(min_length=1, max_length=200)
    information_cutoff: AwareDatetime
    scenario_horizon: date
    scenario_rationale: str = Field(min_length=30, max_length=4000, pattern=r"\S")
    scenario_source_ids: list[str] = Field(min_length=1, max_length=10)
    assumptions: ComparisonAssumptions
    candidates: list[InstrumentCandidate] = Field(min_length=1, max_length=8)
    stock_reference: (
        Annotated[DatasetStockReference | AssumedStockReference, Field(discriminator="kind")] | None
    ) = None


def _time(value, name):
    try:
        return TypeAdapter(AwareDatetime).validate_python(value)
    except (ValueError, TypeError) as exc:
        raise DomainError(
            "COMPARISON_TIME", f"{name} must be an explicit aware timestamp."
        ) from exc


def _available(artifact, cutoff):
    if _time(artifact["created_at"], "Source retention time") > cutoff:
        raise DomainError(
            "INPUT_AFTER_CUTOFF", "A source was retained after the requested information cutoff."
        )
    # Source kinds with an acquisition contract expose a separate receipt time.
    # Arbitrary evidence does not: its retention time is the conservative boundary.
    content = artifact["content"]
    if isinstance(content, dict):
        for key in ("received_at", "retrieved_at"):
            if content.get(key) is not None and _time(content[key], key) > cutoff:
                raise DomainError(
                    "INPUT_AFTER_CUTOFF", "A source was acquired after the information cutoff."
                )


def _stock(research, spec, underlying, case_id, cutoff):
    if spec is None:
        return None, None
    if isinstance(spec, AssumedStockReference):
        return {
            "underlying": underlying,
            "price": str(spec.price),
            "observed_at": None,
            "received_at": None,
            "observation_session": None,
            "source": "Investigator-supplied assumption; no market observation",
            "assumption": True,
            "rationale": spec.rationale,
            "quantity": spec.quantity,
        }, None
    source = research.artifact(spec.dataset_id, kind="dataset", case_id=case_id)
    _available(source, cutoff)
    try:
        snapshot = MarketSnapshot.model_validate(source["content"])
    except ValueError as exc:
        raise DomainError(
            "STOCK_REFERENCE", "Stock source is not a valid saved market snapshot."
        ) from exc
    if snapshot.symbol != underlying:
        raise DomainError("STOCK_REFERENCE", "Stock reference must use the same underlying.")
    # Daily bars carry a session, not the precise time the close became known.
    # Conservatively exclude the cutoff's date, even after the apparent close.
    if spec.session >= cutoff.date():
        raise DomainError("STOCK_REFERENCE_TIME", "Choose a session before the cutoff's UTC date.")
    match = next(
        ((i, bar) for i, bar in enumerate(snapshot.bars) if bar.session == spec.session), None
    )
    if match is None:
        raise DomainError("STOCK_REFERENCE", "The chosen stock session is absent from the dataset.")
    index, bar = match
    return {
        "underlying": underlying,
        "price": str(bar.close),
        "observed_at": None,
        "observation_session": bar.session.isoformat(),
        "received_at": snapshot.retrieved_at.isoformat(),
        "source": snapshot.source,
        "source_path": f"/bars/{index}/close",
        "source_artifact_id": source["id"],
        "assumption": snapshot.price_basis != "raw_no_corporate_actions",
        "source_price_basis": snapshot.price_basis,
        "share_basis_assumption": spec.share_basis_assumption,
        "rationale": spec.rationale,
        "quantity": spec.quantity,
        "corporate_actions_checked": snapshot.corporate_actions_checked,
        "corporate_actions": [a.model_dump(mode="json") for a in snapshot.corporate_actions],
        "limitations": [
            "The observed dataset close is used as a hypothetical entry reference; "
            "no share-basis conversion is inferred and it is not a current ask.",
            "No synchronized stock/options snapshot, dividend return "
            "or future action adjustment is established.",
        ],
    }, source


def save_instrument_comparison(research, args, *, case_id, context=None, now=None):
    if research.settings.read_only:
        raise DomainError("READ_ONLY", "Read-only deployments cannot save comparisons.", 403)
    if context:
        context.check_cancelled()
        if context.case_id != case_id:
            raise DomainError("ARTIFACT_CASE", "Comparison belongs to the current case.")
    if research.store.get_case(case_id)["status"] == "cancelled":
        raise DomainError("CANCELLED", "This investigation has been cancelled.", 409)
    current = now or datetime.now(UTC)
    cutoff = args.information_cutoff.astimezone(UTC)
    if cutoff > current or args.scenario_horizon <= cutoff.date():
        raise DomainError(
            "COMPARISON_TIME", "The cutoff cannot be in the future and expiration must follow it."
        )
    hypothesis = research.artifact(args.hypothesis_id, kind="hypothesis", case_id=case_id)
    if not isinstance(hypothesis["content"], dict):
        raise DomainError("HYPOTHESIS_SCHEMA", "Use a structured saved hypothesis.")
    chain = research.artifact(args.chain_artifact_id, kind="options_chain", case_id=case_id)
    sources = [
        research.artifact(aid, case_id=case_id) for aid in dict.fromkeys(args.scenario_source_ids)
    ]
    for source in [hypothesis, chain, *sources]:
        _available(source, cutoff)
    content = chain["content"]
    if not isinstance(content, dict) or content.get("schema_version") != "options_chain.v1":
        raise DomainError("CHAIN_SCHEMA", "Use a saved options_chain.v1 observation.")
    if content.get("expiration") != args.scenario_horizon.isoformat():
        raise DomainError(
            "COMPARISON_HORIZON", "The scenario horizon must equal the saved chain's expiration."
        )
    received = _time(content.get("received_at"), "Chain receipt")
    acquired = _time(content.get("acquisition_started_at"), "Chain acquisition start")
    if acquired > received or received > cutoff:
        raise DomainError(
            "COMPARISON_TIME", "Chain acquisition times are inconsistent with the cutoff."
        )
    stock, stock_artifact = _stock(
        research, args.stock_reference, content.get("underlying"), case_id, cutoff
    )
    try:
        result = compare_instruments(args.assumptions, args.candidates, content, stock)
    except (ValueError, ArithmeticError) as exc:
        raise DomainError(
            "COMPARISON_INPUT", "Comparison inputs are malformed or unsupported."
        ) from exc
    inputs = list(
        {
            a["id"]: a
            for a in [hypothesis, chain, *sources, *([stock_artifact] if stock_artifact else [])]
        }.values()
    )
    synthetic = any(
        a["metadata"].get("synthetic") is True
        or (isinstance(a["content"], dict) and a["content"].get("synthetic") is True)
        for a in inputs
    )
    result.update(
        {
            "title": args.title,
            "purpose": args.purpose,
            "information_cutoff": cutoff.isoformat(),
            "scenario_horizon": args.scenario_horizon.isoformat(),
            "scenario_rationale": args.scenario_rationale,
            "synthetic": synthetic,
            "execution_eligible": False,
            "hypothesis": {
                **artifact_ref(hypothesis),
                "created_at": hypothesis["created_at"],
                "prediction": hypothesis["content"].get("prediction"),
                "status": hypothesis["content"].get("status"),
            },
            "source_bindings": {
                "hypothesis": artifact_ref(hypothesis),
                "chain": artifact_ref(chain),
                "scenario_sources": [artifact_ref(a) for a in sources],
                "stock": artifact_ref(stock_artifact) if stock_artifact else None,
            },
            "timing": {
                "chain_received_at": content["received_at"],
                "acquisition_started_at": content["acquisition_started_at"],
                "delay_seconds": content.get("delay_seconds"),
                "atomic_snapshot": False,
                "stock_reference": stock,
            },
        }
    )
    metadata = {
        "inputs": [artifact_ref(a) for a in inputs],
        "request": args.model_dump(mode="json"),
        "execution_eligible": False,
        "synthetic": synthetic,
        "scope": "Conditional expiration arithmetic; "
        "assumptions are not validated forecasts or fills.",
    }
    if context:
        return research.save(
            context, "instrument_comparison", args.title, result, metadata, require_active_case=True
        )
    return research.store.put_artifact(
        case_id,
        None,
        "instrument_comparison",
        args.title,
        result,
        metadata,
        require_active_case=True,
    )


def _tool(research, ctx, args):
    return compact_artifact(
        save_instrument_comparison(research, args, case_id=ctx.case_id, context=ctx)
    )


def register_instrument_tools(registry, research):
    registry.register(
        "compare_instruments",
        "Save a hypothesis-linked comparison of cash, stock and nominated long options/debit "
        "spreads under one capital budget and shared expiration scenarios. Resolve option "
        "prices from a saved chain's asks/bids; do not copy or override them. Supply explicit "
        "fees, cash return, price stress, standard-contract assumptions and scenario rationale "
        "with sources. A prior-session stock dataset close with an explicit share-basis "
        "assumption, or a visibly assumed price, may "
        "serve as the stock reference. Horizon must equal expiry; cutoff must follow source "
        "retention. Specify whole quantities or omit them for the maximum affordable amount; "
        "each alternative uses its own budget with unused cash carried. "
        "Keeps unavailable candidates and same-quantity adverse costs. "
        "Probabilities are supplied assumptions, not inferred odds; report does not select a "
        "winner, establish synchronized prices, simulate fills or authorize orders. Inspect "
        "the saved report with read_artifact, then revise assumptions or collect missing evidence.",
        InstrumentComparisonInput,
        ALL_ROLES,
        partial(_tool, research),
        side_effect="artifact",
    )
