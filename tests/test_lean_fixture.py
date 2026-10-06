"""Check fixture provenance and bytes; native LEAN parsing is a separate CI gate."""

import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lean_fixture", ROOT / "examples/engine_spikes/lean_fixture.py"
)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


@pytest.fixture
def source_data(tmp_path):
    source = tmp_path / "Lean" / "Data"
    # Deliberate local stand-ins: these tests do not claim to run LEAN's parser.
    for name, content in (
        (fixture.METADATA_FILES[0], b'{"entries": {}}\n'),
        (fixture.METADATA_FILES[1], b"# synthetic static metadata stand-in\n"),
        ("equity/usa/daily/spy.zip", b"UPSTREAM_MARKET_PRICE_MUST_NOT_BE_COPIED"),
        ("equity/usa/map_files/test.csv", b"UPSTREAM_TEST_IDENTITY_MUST_NOT_BE_COPIED"),
        ("market-hours/unrequested.csv", b"UNREQUESTED_FILE_MUST_NOT_BE_COPIED"),
    ):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return source


def files(directory):
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def records(directory):
    result = {}
    for path in directory.rglob("*.zip"):
        with ZipFile(path) as archive:
            for member in archive.namelist():
                result[(path.relative_to(directory).as_posix(), member)] = (
                    archive.read(member).decode("ascii").splitlines()
                )
    return result


@pytest.mark.parametrize("scenario", fixture.SCENARIOS)
def test_fixtures_are_byte_deterministic_and_all_hashes_match(tmp_path, source_data, scenario):
    first, second = tmp_path / "first", tmp_path / "second"
    manifest = fixture.build_fixture(scenario, first, source_data)
    assert fixture.build_fixture(scenario, second, source_data) == manifest
    assert files(first) == files(second)
    assert json.loads((first / "fixture-manifest.json").read_text()) == manifest
    assert manifest["native_parser_verified_by_generator"] is False
    assert {entry["path"] for entry in manifest["files"]} == (
        set(files(first)) - {"fixture-manifest.json"}
    )
    for entry in manifest["files"]:
        raw = (first / entry["path"]).read_bytes()
        assert len(raw) == entry["bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        if entry["path"].endswith(".zip"):
            with ZipFile(first / entry["path"]) as archive:
                for member in entry["members"]:
                    content = archive.read(member["name"])
                    assert len(content.splitlines()) == member["rows"]
                    assert hashlib.sha256(content).hexdigest() == member["sha256"]
                for info in archive.infolist():
                    assert info.date_time == (1980, 1, 1, 0, 0, 0)
                    assert info.compress_type == ZIP_STORED
    written = records(first)
    for event in manifest["events"]:
        local = datetime.fromisoformat(event["local_time"])
        assert local.utcoffset() == timedelta(hours=-5)
        assert local.astimezone(UTC) == datetime.fromisoformat(event["utc_time"])
        row = written[(event["archive"], event["member"])][event["line_number"] - 1]
        assert (
            int(row.split(",")[0]) == (local.hour * 3600 + local.minute * 60 + local.second) * 1000
        )


def test_only_allowlisted_metadata_is_copied_and_identity_is_synthetic(tmp_path, source_data):
    before = files(source_data)
    destination = tmp_path / "fixture"
    manifest = fixture.build_fixture("market_itm", destination, source_data)
    assert files(source_data) == before
    for name in fixture.METADATA_FILES:
        assert (destination / name).read_bytes() == before[name]
    for content in files(destination).values():
        assert b"MUST_NOT_BE_COPIED" not in content
    assert (destination / "equity/usa/map_files/test.csv").read_text() == (
        "20260115,test\n20501231,test\n"
    )
    assert (destination / "equity/usa/factor_files/test.csv").read_text() == (
        "20260115,1,1,0\n20501231,1,1,0\n"
    )
    provenance = manifest["metadata_provenance"]
    assert provenance["expected_lean_commit"] == fixture.LEAN_COMMIT
    assert {entry["path"] for entry in provenance["files"]} == set(fixture.METADATA_FILES)
    for entry in provenance["files"]:
        assert entry["sha256"] == hashlib.sha256(before[entry["path"]]).hexdigest()
        assert fixture.LEAN_COMMIT in entry["source_url"]


@pytest.mark.parametrize("scenario", ["native_itm", "market_itm", "market_shortfall"])
def test_original_trade_tape_names_columns_prices_and_liquidity(tmp_path, source_data, scenario):
    destination = tmp_path / "fixture"
    manifest = fixture.build_fixture(scenario, destination, source_data)
    assert len(manifest["events"]) == 5
    assert records(destination) == {
        (
            "equity/usa/tick/test/20260116_trade.zip",
            "20260116_test_Trade_Tick.csv",
        ): [
            "57595000,1000000,100,,,0",
            "57600000,1100000,100,,,0",
            "57601000,1100000,100,,,0",
        ],
        (
            "option/usa/tick/test/20260116_quote_american.zip",
            "20260116_test_tick_quote_american_call_1000000_20260116.csv",
        ): ["57596000,20000,1,20000,1,,0", "57597000,20000,10,20000,10,,0"],
    }
    assert manifest["events"][0]["utc_time"] == "2026-01-16T20:59:55Z"
    assert manifest["events"][-1]["utc_time"] == "2026-01-16T21:00:01Z"


def test_otm_changes_only_terminal_underlying_prices(tmp_path, source_data):
    destination = tmp_path / "fixture"
    manifest = fixture.build_fixture("market_otm", destination, source_data)
    underlying = [event for event in manifest["events"] if event["security_type"] == "equity"]
    assert [event["price"] for event in underlying] == ["100.00", "90.00", "90.00"]
    assert [event["tick_type"] for event in underlying] == ["trade"] * 3


@pytest.mark.parametrize(
    "scenario,price", [("market_quote_only", "110.00"), ("market_stale_trade", "90.00")]
)
def test_missing_and_stale_trade_cases_never_synthesize_current_trades(
    tmp_path, source_data, scenario, price
):
    destination = tmp_path / "fixture"
    manifest = fixture.build_fixture(scenario, destination, source_data)
    equity = [event for event in manifest["events"] if event["security_type"] == "equity"]
    quotes = [event for event in equity if event["tick_type"] == "quote"]
    trades = [event for event in equity if event["tick_type"] == "trade"]
    assert len(quotes) == 3
    assert {event["bid"] for event in quotes} == {price}
    assert {event["ask"] for event in quotes} == {price}
    quote_rows = records(destination)[
        ("equity/usa/tick/test/20260116_quote.zip", "20260116_test_Quote_Tick.csv")
    ]
    assert [len(row.split(",")) for row in quote_rows] == [8, 8, 8]
    assert not (destination / "equity/usa/tick/test/20260116_trade.zip").exists()
    if scenario == "market_quote_only":
        assert trades == []
        assert not list(destination.glob("equity/usa/tick/test/*_trade.zip"))
    else:
        assert len(trades) == 1
        assert trades[0]["utc_time"] == "2026-01-15T20:59:55Z"
        assert trades[0]["price"] == "110.00"
        assert records(destination)[
            ("equity/usa/tick/test/20260115_trade.zip", "20260115_test_Trade_Tick.csv")
        ] == ["57595000,1100000,100,,,0"]


def test_vertical_uses_exact_refresh_grid_and_no_expired_option_quotes(tmp_path, source_data):
    destination = tmp_path / "fixture"
    manifest = fixture.build_fixture("vertical_assignment", destination, source_data)
    assert len(manifest["events"]) == 328
    contracts = manifest["contracts"]
    assert [contract["strike"] for contract in contracts] == ["100", "120"]
    assert all(contract["expiry_date"] == "2026-01-16" for contract in contracts)
    expected_times = ["09:31:00", "09:31:01"]
    point = datetime(2026, 1, 15, 9, 35)
    while point <= datetime(2026, 1, 15, 15, 55):
        expected_times.append(point.strftime("%H:%M:%S"))
        point += timedelta(minutes=5)
    for symbol in ("TEST", "TEST-20260116-C100", "TEST-20260116-C120"):
        events = [
            event
            for event in manifest["events"]
            if event["symbol"] == symbol and event["tick_type"] == "quote"
        ]
        jan15 = [
            event["local_time"][11:19]
            for event in events
            if event["local_time"].startswith("2026-01-15")
        ]
        assert jan15 == expected_times
        jan16 = [
            event["local_time"][11:19]
            for event in events
            if event["local_time"].startswith("2026-01-16")
        ]
        assert jan16 == (
            ["09:31:00", "15:59:55", "16:00:00", "16:00:01"]
            if symbol == "TEST"
            else ["09:31:00", "15:59:55"]
        )
    option_events = [event for event in manifest["events"] if event["security_type"] == "option"]
    assert all(event["utc_time"] < "2026-01-16T21:00:00Z" for event in option_events)
    assert all(event["tick_type"] == "quote" for event in option_events)
    for (_, member), rows in records(destination).items():
        if "call_1000000" in member:
            assert all(
                row.split(",")[1:] == ["99000", "10", "101000", "10", "", "0"] for row in rows
            )
        elif "call_1200000" in member:
            assert all(row.split(",")[1:] == ["9000", "10", "11000", "10", "", "0"] for row in rows)


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "dangling_symlink"])
def test_existing_destination_is_rejected_without_changes(tmp_path, source_data, kind):
    destination = tmp_path / "exists"
    if kind == "directory":
        destination.mkdir()
    elif kind == "file":
        destination.write_bytes(b"existing file")
    else:
        target = tmp_path / "target"
        if kind == "symlink":
            target.mkdir()
        destination.symlink_to(target)
    with pytest.raises(FileExistsError):
        fixture.build_fixture("market_itm", destination, source_data)
    if kind == "directory":
        assert list(destination.iterdir()) == []
    elif kind == "file":
        assert destination.read_bytes() == b"existing file"
    else:
        assert destination.is_symlink()


def test_unknown_scenario_and_missing_metadata_fail_without_creating_output(tmp_path, source_data):
    destination = tmp_path / "fixture"
    with pytest.raises(ValueError, match="Unknown"):
        fixture.build_fixture("not_a_case", destination, source_data)
    assert not destination.exists()
    (source_data / fixture.METADATA_FILES[1]).unlink()
    with pytest.raises(ValueError, match="Required static metadata"):
        fixture.build_fixture("market_itm", destination, source_data)
    assert not destination.exists()
