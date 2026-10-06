"""Write synthetic LEAN tick fixtures, never copying upstream market prices.

Import ``build_fixture(scenario, destination, source_data)`` or run this module:
    python examples/engine_spikes/lean_fixture.py market_itm --output NEW_DIRECTORY \
        --source-data /path/to/pinned/Lean/Data

Formats were inspected in the pinned LeanData.cs, Tick.cs, MapFileRow.cs and
CorporateFactorRow.cs. This generator does not execute LEAN's native parser.
The caller must verify that source_data belongs to the pinned source checkout.
"""

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo
from zoneinfo import ZoneInfo

LEAN_COMMIT = "705b9551be1aaa821c7f77896a7eb8fcd07b92ee"
SOURCE_URL = f"https://github.com/QuantConnect/Lean/blob/{LEAN_COMMIT}"
TIMEZONE = "America/New_York"
EXPIRY = "2026-01-16"
SCENARIOS = (
    "native_itm",
    "market_itm",
    "market_otm",
    "market_shortfall",
    "market_quote_only",
    "market_stale_trade",
    "vertical_assignment",
)
METADATA_FILES = (
    "market-hours/market-hours-database.json",
    "symbol-properties/symbol-properties-database.csv",
)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _event(day, clock, *, strike=None, price=None, bid=None, ask=None, size=100):
    local = datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=ZoneInfo(TIMEZONE))
    event = {
        "local_time": local.isoformat(),
        "utc_time": local.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "security_type": "equity" if strike is None else "option",
        "symbol": "TEST" if strike is None else f"TEST-20260116-C{strike}",
        "tick_type": "trade" if price is not None else "quote",
    }
    if strike is not None:
        event["strike"] = str(strike)
    if price is not None:
        event.update(price=price, quantity=size)
    else:
        event.update(bid=bid, ask=ask, bid_size=size, ask_size=size)
    return event


def _events(scenario):
    if scenario == "vertical_assignment":
        times = [("2026-01-15", "09:31:00"), ("2026-01-15", "09:31:01")]
        point = datetime(2026, 1, 15, 9, 35)
        while point <= datetime(2026, 1, 15, 15, 55):
            times.append(("2026-01-15", point.strftime("%H:%M:%S")))
            point += timedelta(minutes=5)
        times += [(EXPIRY, "09:31:00"), (EXPIRY, "15:59:55")]
        events = []
        for day, clock in times:
            events.extend(
                (
                    _event(day, clock, price="110.00"),
                    _event(day, clock, bid="110.00", ask="110.00"),
                    _event(day, clock, strike=100, bid="9.90", ask="10.10", size=10),
                    _event(day, clock, strike=120, bid="0.90", ask="1.10", size=10),
                )
            )
        for clock in ("16:00:00", "16:00:01"):
            events.extend(
                (
                    _event(EXPIRY, clock, price="110.00"),
                    _event(EXPIRY, clock, bid="110.00", ask="110.00"),
                )
            )
    else:
        events = [
            _event(EXPIRY, "15:59:56", strike=100, bid="2.00", ask="2.00", size=1),
            _event(EXPIRY, "15:59:57", strike=100, bid="2.00", ask="2.00", size=10),
        ]
        spot = "90.00" if scenario in {"market_otm", "market_stale_trade"} else "110.00"
        quotes_only = scenario in {"market_quote_only", "market_stale_trade"}
        for clock in ("15:59:55", "16:00:00", "16:00:01"):
            if quotes_only:
                events.append(_event(EXPIRY, clock, bid=spot, ask=spot))
            else:
                price = "100.00" if clock == "15:59:55" else spot
                events.append(_event(EXPIRY, clock, price=price))
        if scenario == "market_stale_trade":
            events.append(_event("2026-01-15", "15:59:55", price="110.00"))
    # A canonical inventory order, not a promise of cross-subscription delivery order.
    return sorted(
        events, key=lambda event: (event["utc_time"], event["symbol"], event["tick_type"])
    )


def _scaled(value):
    return str(int(Decimal(value) * 10000))


def _tick_record(event):
    local = datetime.fromisoformat(event["local_time"])
    day = local.strftime("%Y%m%d")
    milliseconds = str(((local.hour * 60 + local.minute) * 60 + local.second) * 1000)
    kind = event["tick_type"]
    security = event["security_type"]
    if security == "equity":
        archive = f"equity/usa/tick/test/{day}_{kind}.zip"
        # LeanData.GenerateZipEntryName uses the enum spelling for equity ticks.
        member = f"{day}_test_{kind.title()}_Tick.csv"
    else:
        archive = f"option/usa/tick/test/{day}_{kind}_american.zip"
        member = f"{day}_test_tick_{kind}_american_call_{_scaled(event['strike'])}_20260116.csv"
    if kind == "trade":
        fields = [milliseconds, _scaled(event["price"]), str(event["quantity"]), "", "", "0"]
    else:
        fields = [
            milliseconds,
            _scaled(event["bid"]),
            str(event["bid_size"]),
            _scaled(event["ask"]),
            str(event["ask_size"]),
            "",  # Empty exchange code, not an invented real execution venue.
        ]
        if security == "equity":
            fields.append("")  # Equity quotes include a sale-condition field.
        fields.append("0")  # Not suspicious.
    return archive, member, ",".join(fields) + "\n"


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def build_fixture(scenario: str, destination: Path, source_data: Path) -> dict:
    """Create a new standalone data directory and return its written manifest.

    Only two explicitly named static metadata files are read from source_data.
    No existing destination, including an empty directory or symlink, is reused.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown LEAN fixture scenario: {scenario}")
    destination, source_data = Path(destination), Path(source_data)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Fixture destination already exists: {destination}")
    metadata = {}
    for relative in METADATA_FILES:
        source = source_data / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Required static metadata must be a regular file: {source}")
        metadata[relative] = source.read_bytes()

    events = _events(scenario)
    archives = defaultdict(lambda: defaultdict(list))
    for event in events:
        archive, member, row = _tick_record(event)
        rows = archives[archive][member]
        rows.append(row)
        event.update(archive=archive, member=member, line_number=len(rows))

    destination.mkdir(parents=True, exist_ok=False)
    records = []

    def write_file(relative, content, origin):
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        records.append(
            {"path": relative, "bytes": len(content), "sha256": _sha256(content), "origin": origin}
        )

    for relative, content in metadata.items():
        write_file(relative, content, "upstream_static_metadata")
    # Native map and corporate-factor row formats. TEST never renames or adjusts,
    # and its distant last map row prevents an artificial fixture-end delisting.
    write_file(
        "equity/usa/map_files/test.csv",
        b"20260115,test\n20501231,test\n",
        "synthetic_identity_metadata",
    )
    write_file(
        "equity/usa/factor_files/test.csv",
        b"20260115,1,1,0\n20501231,1,1,0\n",
        "synthetic_identity_metadata",
    )
    for relative, members in sorted(archives.items()):
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        member_records = []
        # Stored entries avoid compression-version differences as well as timestamps.
        with ZipFile(path, "x", compression=ZIP_STORED) as archive:
            for name, rows in sorted(members.items()):
                content = "".join(rows).encode("ascii")
                info = ZipInfo(name, date_time=ZIP_TIMESTAMP)
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = ZIP_STORED
                archive.writestr(info, content)
                member_records.append({"name": name, "rows": len(rows), "sha256": _sha256(content)})
        content = path.read_bytes()
        records.append(
            {
                "path": relative,
                "bytes": len(content),
                "sha256": _sha256(content),
                "origin": "synthetic_ticks",
                "members": member_records,
            }
        )

    manifest = {
        "schema_version": 1,
        "synthetic": True,
        "scenario": scenario,
        "timezone": TIMEZONE,
        "resolution": "tick",
        "market": "usa",
        "price_scale": 10000,
        "native_parser_verified_by_generator": False,
        "metadata_provenance": {
            "expected_lean_commit": LEAN_COMMIT,
            "checkout_pin_verification": "Caller responsibility; files are hashed below.",
            "files": [
                {
                    "path": relative,
                    "source_url": f"{SOURCE_URL}/Data/{relative}",
                    "sha256": _sha256(content),
                }
                for relative, content in metadata.items()
            ],
        },
        "format_sources": [
            f"{SOURCE_URL}/{path}"
            for path in (
                "Common/Util/LeanData.cs",
                "Common/Data/Market/Tick.cs",
                "Common/Data/Auxiliary/MapFileRow.cs",
                "Common/Data/Auxiliary/CorporateFactorRow.cs",
            )
        ],
        "contracts": [
            {
                "underlying": "TEST",
                "right": "call",
                "style": "american",
                "strike": str(strike),
                "expiry_date": EXPIRY,
                "currency": "USD",
                "premium_multiplier": 100,
                "deliverable_shares": 100,
                "adjusted": False,
            }
            for strike in ([100, 120] if scenario == "vertical_assignment" else [100])
        ],
        "rules": {
            "calendar": "Unmodified upstream market hours; no forced-open exchange.",
            "terminal_ticks": (
                "Underlying ticks at 16:00:00 and 16:00:01 are supplied tape events. "
                "Native subscriptions may filter them; no option ticks occur at/after 16:00."
            ),
            "ordering": "Events are a canonical inventory, not cross-subscription delivery order.",
            "sources": "All prices are invented; upstream market prices are never copied.",
            "identity": "TEST map is constant through 2050-12-31; all factors are 1.",
            "vertical_refresh": (
                "January 15: 09:31:00, 09:31:01, then 09:35 to 15:55 every five minutes. "
                "January 16: 09:31:00 and 15:59:55; terminal underlying ticks only."
            ),
        },
        "events": events,
        "files": sorted(records, key=lambda record: record["path"]),
    }
    (destination / "fixture-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-data", required=True, type=Path)
    args = parser.parse_args(argv)
    build_fixture(args.scenario, args.output, args.source_data)
    print(f"Synthetic fixture written: {args.output / 'fixture-manifest.json'}")


if __name__ == "__main__":
    main()
