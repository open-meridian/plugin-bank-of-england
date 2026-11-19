"""The plugin's own conversion of the Bank of England's recorded answers."""

from __future__ import annotations

import asyncio
import io
import zipfile
from datetime import date
from pathlib import Path

from meridian.operations import as_decimal
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.suites import Recorder

from bank_of_england.answers import covers, parse_curves
from bank_of_england.portal import ARCHIVES, Fetched, SyntheticPortal
from bank_of_england.series import months_of, tenor_of

from conftest import AT, CURVES, FX, GBP, HELD, INSTANCE, feed, fx_want, resolving, want


def checked(tmp: Path, *left_out: str) -> Recorder:
    plugin = resolving(Recorder(INSTANCE), *left_out)
    asyncio.run(feed(tmp, plugin).check())
    return plugin


def rates_of(plugin: Recorder, subject: str) -> list[ops.Rate]:
    return [
        r
        for b in plugin.on("RecordRates")
        for r in b.rates
        if r.meta.subjects[0].entity_id == subject
    ]


def heard(tmp: Path, *asked: object, plugin: Recorder | None = None) -> Recorder:
    """The rates checked, then each want heard."""
    held = plugin or resolving(Recorder(INSTANCE))
    work = feed(tmp, held)
    asyncio.run(work.check())
    for one in asked:
        held.answer("ObservationsWanted", lambda _, w=one: w.message)  # type: ignore[misc]
        asyncio.run(held.hear(work))
    return held


def test_sonia_a_fixing_act_365_simple(tmp_path: Path) -> None:
    sonia = rates_of(checked(tmp_path), HELD["SONIA"])
    day = next(r for r in sonia if r.meta.business_date == "2026-11-17")
    assert day.kind == ops.RATE_KIND_FIXING and str(as_decimal(day.value.value)) == "3.984"
    assert day.convention.day_count == ops.DAY_COUNT_ACT_365_FIXED
    assert day.convention.compounding == ops.COMPOUNDING_SIMPLE
    assert {p.percentile: str(as_decimal(p.value)) for p in day.percentiles} == {
        10: "3.95", 25: "3.97", 75: "4", 90: "4",
    }  # fmt: skip
    assert not day.meta.source_times and day.meta.raw.key.startswith("responses/")
    assert "2026-11-18" not in {r.meta.business_date for r in sonia}


def test_the_index_and_bank_rate(tmp_path: Path) -> None:
    plugin = checked(tmp_path)
    index = next(
        r
        for r in rates_of(plugin, HELD["SONIA compounded index"])
        if r.meta.business_date == "2026-11-18"
    )
    assert index.kind == ops.RATE_KIND_INDEX_LEVEL and index.value.index_base == "2018-04-23=100"
    assert str(as_decimal(index.value.value)) == "122.08507868"
    bank_rate = rates_of(plugin, HELD["Bank Rate"])
    assert bank_rate and all(r.kind == ops.RATE_KIND_FIXING for r in bank_rate)
    assert {str(as_decimal(r.value.value)) for r in bank_rate} == {"4"}


def test_the_rates_alone_are_pushed(tmp_path: Path) -> None:
    plugin = checked(tmp_path)
    assert not rates_of(plugin, HELD["OIS spot curve"]) and not plugin.on("RecordPrices")
    datasets = {r.meta.source.dataset for b in plugin.on("RecordRates") for r in b.rates}
    assert datasets == {f"{INSTANCE}:boe_rates"}


def test_a_curve_wanted_its_spot_points_continuously_compounded(tmp_path: Path) -> None:
    plugin = heard(
        tmp_path,
        want("w-1", [HELD["OIS spot curve"]], day="2026-11-18", dataset=CURVES),
        want("w-2", [HELD["Gilt nominal spot curve"]], day="2026-11-18", dataset=CURVES),
    )
    ois = {r.meta.row_key: r for r in rates_of(plugin, HELD["OIS spot curve"])}
    gilt = rates_of(plugin, HELD["Gilt nominal spot curve"])
    assert len(ois) == 100 and len(gilt) == 127
    ten = next(
        r for r in ois.values() if (r.tenor.count, r.tenor.unit) == (10, ops.TENOR_UNIT_YEAR)
    )
    assert (
        ten.kind == ops.RATE_KIND_ZERO and str(as_decimal(ten.value.value)) == "4.804483138357444"
    )
    assert ten.convention.compounding == ops.COMPOUNDING_CONTINUOUS
    assert ten.meta.source.dataset == CURVES and not ten.meta.HasField("raw")
    forty = [r for r in gilt if (r.tenor.count, r.tenor.unit) == (40, ops.TENOR_UNIT_YEAR)]
    assert str(as_decimal(forty[0].value.value)) == "5.3963056778704432"
    against = {
        b.want_id for b in plugin.on("RecordRates") if b.rates[0].meta.source.dataset == CURVES
    }
    assert against == {"w-1", "w-2"}


def test_the_exchange_rates_wanted_sterlings_price_never_inverted(tmp_path: Path) -> None:
    plugin = heard(tmp_path, fx_want("w-fx", "2026-11-18"))
    prices = [p for b in plugin.on("RecordPrices") for p in b.prices]
    assert len(prices) == 26  # the lev states none
    dollar = next(p for p in prices if p.meta.row_key == "GBPUSD:2026-11-18")
    assert dollar.meta.subjects[0].entity_id == GBP and dollar.kind == ops.PRICE_KIND_CLOSE
    assert str(as_decimal(dollar.price.amount)) == "1.3148" and dollar.price.currency_code == "USD"
    assert dollar.meta.source.dataset == FX and not dollar.meta.HasField("raw")


def test_the_restricted_answers_are_never_kept(tmp_path: Path) -> None:
    work = feed(tmp_path)
    asyncio.run(work.check())
    kept = len(work.raw.keys())
    plugin = heard(
        tmp_path / "w",
        fx_want("w-fx", "2026-11-18"),
        want("w-c", [HELD["OIS spot curve"]], day="2026-11-17", dataset=CURVES),
    )
    assert plugin.on("RecordPrices") and kept == 1
    assert all("rates-" in k for k in feed(tmp_path / "w").raw.keys())  # noqa: SIM118 - RawStore.keys


def test_a_day_before_the_latest_file_read_from_the_archive(tmp_path: Path) -> None:
    class Archived(SyntheticPortal):
        """The archive answered with the recorded workbooks under its names."""

        async def get(self, path: str) -> Fetched:
            if path not in ARCHIVES.values():
                return await super().get(path)
            self.asked.append(path)
            held = zipfile.ZipFile(io.BytesIO(self.recordings["curves"].body))
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as archive:
                for name in held.namelist():
                    stem = name.removesuffix(" current month.xlsx")
                    archive.writestr(f"{stem}_2025 to present.xlsx", held.read(name))
                    archive.writestr(f"{stem}_2016 to 2024.xlsx", b"not a workbook")
            return Fetched(path, 200, out.getvalue(), AT)

    plugin = resolving(Recorder(INSTANCE))
    portal = Archived(lambda: AT)
    work = feed(tmp_path, plugin, portal=portal)
    asyncio.run(work.check())
    read, key = asyncio.run(work.read("curves", date(2026, 10, 30), date(2026, 11, 3)))
    assert key == "" and sorted(set(ARCHIVES.values())) == sorted(portal.asked[-2:])
    assert read.days == [date(2026, 11, 2), date(2026, 11, 3)] and not read.unread


def test_tenors_and_archive_years() -> None:
    assert tenor_of(months_of("1.0000000400000015", "months") or 0) == "1M"
    assert tenor_of(months_of("0.5", "years") or 0) == "6M"
    assert tenor_of(months_of("40", "years") or 0) == "40Y"
    assert months_of("8.3333329999999997E-2", "years") == 1 and months_of("x", "years") is None
    assert covers("OIS daily data_2016 to 2024.xlsx", date(2020, 1, 1), date(2020, 1, 2))
    assert not covers("OIS daily data_2016 to 2024.xlsx", date(2025, 1, 1), date(2025, 1, 2))
    assert covers("OIS daily data_2025 to present.xlsx", date(2026, 1, 1), date(2026, 1, 2))
    assert covers("OIS daily data current month.xlsx", date(1990, 1, 1), date(1990, 1, 1))
    assert not parse_curves(
        SyntheticPortal(lambda: AT).recordings["curves"].body,
        "curves",
        date(2026, 10, 1),
        date(2026, 10, 31),
    ).observations


def test_a_record_not_held_is_reported_missing_and_waits(tmp_path: Path) -> None:
    plugin = checked(tmp_path, "Bank Rate", "OIS spot curve")
    missed = {i.value for p in plugin.on("ReportMissingInstrument") for i in p.identifiers}
    assert missed == {"Bank Rate", "OIS spot curve"}
    assert not rates_of(plugin, HELD["Bank Rate"])


def test_wants_declined(tmp_path: Path) -> None:
    plugin = heard(
        tmp_path,
        want("w-1", [HELD["SONIA"]], day="2026-10-01"),
        want("w-2", ["INS-ELSE"], day="2026-10-01"),
        want("w-3", [HELD["SONIA"]], day="2026-10-04"),
        fx_want("w-4", "2026-11-15"),
        want("w-5", [HELD["OIS spot curve"]], day="2026-10-01", dataset=CURVES),
    )
    against = [b for b in plugin.on("RecordRates") if b.want_id == "w-1"]
    assert against and {r.meta.business_date for r in against[0].rates} == {"2026-10-01"}
    reasons = [ops.UnansweredReason.Name(d.reason) for d in plugin.on("DeclineWant")]
    assert reasons == ["UNANSWERED_REASON_NOT_COVERED"] + ["UNANSWERED_REASON_SOURCE_SILENT"] * 3


def test_nothing_recorded_twice_in_a_process(tmp_path: Path) -> None:
    plugin = resolving(Recorder(INSTANCE))
    work = feed(tmp_path, plugin)
    asyncio.run(work.check())
    before = len(plugin.on("RecordRates"))
    asyncio.run(work.check())
    assert len(plugin.on("RecordRates")) == before
