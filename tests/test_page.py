"""The two pages under Manage, and their read tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from meridian.suites import Recorder
from meridian.testing import PageClient

from bank_of_england import page as page_module
from bank_of_england.page import CONNECTION, DATASETS_PAGE, figures, hold, pages

from conftest import CURVES, GBP, HELD, INSTANCE, feed, fx_want, resolving, want


@pytest.fixture
def client(tmp_path: Path) -> PageClient:
    plugin = resolving(Recorder(INSTANCE), "Gilt nominal spot curve")
    work = feed(tmp_path, plugin)
    asyncio.run(work.check())
    for asked in (
        fx_want("w-fx", "2026-11-18"),
        want("w-c", [HELD["OIS spot curve"]], day="2026-11-18", dataset=CURVES),
    ):
        plugin.answer("ObservationsWanted", lambda _, w=asked: w.message)  # type: ignore[misc]
        asyncio.run(plugin.hear(work))
    hold(work)
    return PageClient(pages)


def test_each_page_is_managed_alone(client: PageClient) -> None:
    served = {(r.page.path, r.level): r.response.status for r in client.every_page()}
    assert served == {
        (CONNECTION, "admin"): 200,
        (CONNECTION, "write"): 403,
        (CONNECTION, "read"): 403,
        (DATASETS_PAGE, "admin"): 200,
        (DATASETS_PAGE, "write"): 403,
        (DATASETS_PAGE, "read"): 403,
    }
    client.assert_no_account_data("1.3148", "122.08507868", "3.984", "4.804483138357444")


def test_connection_and_its_sources(client: PageClient) -> None:
    text = client.get(CONNECTION, "admin").text
    assert "No key needed" in text and "Does not stream" in text and "1 record not held" in text
    sources = client.get(CONNECTION, "admin", tab="sources").text
    assert sources.count("<tr data-source=") == 3
    assert "Wed 18 Nov 2026" in sources and sources.count("None: served, not kept") == 2


def test_datasets_and_records(client: PageClient) -> None:
    text = client.get(DATASETS_PAGE, "admin").text
    assert all(f"bank-of-england:{k}" in text for k in ("boe_rates", "boe_curves", "boe_fx"))
    assert text.count("served, not kept") >= 2
    records = client.get(DATASETS_PAGE, "admin", tab="records").text
    assert 'data-code="SONIA"' in records and 'data-code="USD"' in records
    assert 'data-code="GLC Real daily data"' in records and "Source: Bank of England" in records
    searched = client.get(DATASETS_PAGE, "admin", q="SONIA").text
    assert searched.count("<tr data-code=") == 3


def test_the_tools_answer_what_the_pages_show(client: PageClient) -> None:
    data = client.call_tool("read_connection").data
    assert data["mode"] == "Sample data" and [s["dataset"] for s in data["sources"]] == [
        "bank-of-england:boe_rates", "bank-of-england:boe_curves", "bank-of-england:boe_fx",
    ]  # fmt: skip
    read = client.call_tool("read_datasets").data
    held = {r["code"]: r for r in read["records"]}
    assert held["SONIA"]["instrument_id"] == HELD["SONIA"]
    assert held["Gilt nominal spot curve"]["miss"] == "not held: reported missing"
    assert held["USD"]["instrument_id"] == GBP and held["USD"]["latest_day"] == "2026-11-18"
    assert held["OIS spot curve"]["latest_day"] == "2026-11-18"
    assert held["2. fwd curve"]["miss"] == "not carried"


def test_before_the_first_check_and_not_reached(tmp_path: Path) -> None:
    page_module._held.clear()
    assert "Checking the Bank" in PageClient(pages).get(CONNECTION, "admin").text
    work = feed(tmp_path)
    work.status.sources["rates"].error = "https://www.bankofengland.co.uk/boeapps: URLError"
    hold(work)
    text = PageClient(pages).get(CONNECTION, "admin").text
    assert 'state="error"' in text and "Not answering" in text
    sources = PageClient(pages).get(CONNECTION, "admin", tab="sources").text
    assert sources.count("<td>Pulled when wanted") == 2


def test_the_figures_are_the_data_roles(client: PageClient) -> None:
    work = page_module._held["feed"]
    said = figures(work.status, work)
    assert [f.label for f in said][:3] == ["Connection", "Entitled at the vendor", "Stream"]
