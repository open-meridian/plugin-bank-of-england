"""The Bank of England's answers, read as the Bank wrote them.

**The Statistical Interactive Database** (IADB) answers a request for
series as CSV: a header line, `DATE` then each series' code, then one line
a day, its date as `03 Aug 2026`, each series' value as the Bank writes it,
empty where it states none that day: no value, never a zero.

**The yield curve files** are a zip of Excel workbooks (.xlsx), read with
the standard library's zipfile and XML parser alone. Each workbook named for
a curve ("GLC Nominal daily data", "OIS daily data", then `current month` in
the latest file or `_<year> to <year>` in the archive) holds a sheet a view;
the two read here, "3. spot, short end" and "4. spot curve", each state
their maturities on a row headed `months:` or `years:`, then one row a day,
its date an Excel serial number in column A, each point's value in per cent.
A cell holding an error or nothing is no value.

A value is kept as the text the Bank wrote, and read as a `Decimal` from it,
never a float; a value that does not read is kept as not read, and never
recorded.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from .series import SHORT_END, SHORT_END_MONTHS, SPOT_CURVE, WORKBOOKS, months_of, tenor_of

MISSING = {"", "n/a", "NA", ".."}
_SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
#: A workbook's years in the archive: `_2016 to 2024`, `_2025 to present`.
_YEARS = re.compile(r"_(\d{4}) to (\d{4}|present)")


class NotRead(Exception):  # noqa: N818 - what the answer was not
    """An answer that is not what was asked for."""


@dataclass(frozen=True)
class Observation:
    """One value as the Bank stated it: its series (a curve's record code),
    day, text and, for a curve's point, its tenor."""

    series: str
    day: date
    text: str
    tenor: str = ""

    @property
    def value(self) -> Decimal:
        return Decimal(self.text)


@dataclass
class Observations:
    """An answer read: its values in order, and the values that did not read."""

    source: str
    observations: list[Observation] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)

    @property
    def days(self) -> list[date]:
        return sorted({o.day for o in self.observations})

    def on(self, day: date) -> dict[str, Observation]:
        return {o.series: o for o in self.observations if o.day == day}


def _number(text: str) -> bool:
    try:
        return Decimal(text).is_finite()
    except InvalidOperation:
        return False


def parse_iadb(text: str, source: str) -> Observations:
    """An IADB CSV answer, read; NotRead where it is not one."""
    read = Observations(source)
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rows or not rows[0] or rows[0][0].strip() != "DATE":
        raise NotRead(f"the answer is not the database's CSV: {text[:80]!r}")
    header = [h.strip() for h in rows[0]]
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        try:
            day = datetime.strptime(row[0].strip(), "%d %b %Y").date()
        except ValueError:
            read.unread.append(f"{source}: a day {row[0][:20]!r}")
            continue
        for name, stated in zip(header[1:], row[1:], strict=False):
            said = stated.strip()
            if not name or said in MISSING:
                continue
            if not _number(said):
                read.unread.append(f"{name} {day}: {said[:40]!r}")
                continue
            read.observations.append(Observation(name, day, said))
    read.observations.sort(key=lambda o: (o.series, o.day))
    return read


def covers(name: str, start: date, end: date) -> bool:
    """Whether a curve workbook may hold a day from `start` to `end`: the
    latest file's ("current month") always; an archive's by its years."""
    found = _YEARS.search(name)
    if found is None:
        return True
    first = int(found.group(1))
    last = 9999 if found.group(2) == "present" else int(found.group(2))
    return first <= end.year and start.year <= last


def parse_curves(body: bytes, source: str, start: date, end: date) -> Observations:
    """The spot curves from `start` to `end` in a curve file's zip, read;
    NotRead where it is not one."""
    read = Observations(source)
    try:
        held = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as failed:
        raise NotRead(f"the answer is not the curve files' zip: {body[:40]!r}") from failed
    with held:
        names = [n for n in held.namelist() if n.lower().endswith(".xlsx")]
        if not names:
            raise NotRead("the zip holds no workbook")
        for name in names:
            record = next(
                (r for start_of, r in WORKBOOKS.items() if name.startswith(start_of)), None
            )
            if record is None or not covers(name, start, end):
                continue
            try:
                book = zipfile.ZipFile(io.BytesIO(held.read(name)))
            except zipfile.BadZipFile:
                read.unread.append(f"{name}: not a workbook")
                continue
            with book:
                _workbook(book, record.code, start, end, read)
    read.observations.sort(key=lambda o: (o.series, o.day, o.tenor))
    return read


def _workbook(book: zipfile.ZipFile, code: str, start: date, end: date, read: Observations) -> None:
    sheets, epoch = _sheets(book)
    strings = _strings(book)
    for sheet, keep in ((SHORT_END, _short), (SPOT_CURVE, _long)):
        path = sheets.get(sheet)
        if path is None:
            read.unread.append(f"{code}: no sheet {sheet!r}")
            continue
        rows = _rows(book.read(path), strings)
        tenors: dict[str, str] = {}
        for cells in rows:
            unit = cells.get("A", "").strip().rstrip(":")
            if unit in ("months", "years") and not tenors:
                for column, stated in cells.items():
                    months = months_of(stated, unit) if column != "A" else None
                    if months is not None and keep(months):
                        tenors[column] = tenor_of(months)
                continue
            if not tenors:
                continue
            day = _serial(cells.get("A", ""), epoch)
            if day is None or not start <= day <= end:
                continue
            for column, tenor in tenors.items():
                said = cells.get(column, "").strip()
                if said in MISSING:
                    continue
                if not _number(said):
                    read.unread.append(f"{code} {tenor} {day}: {said[:40]!r}")
                    continue
                read.observations.append(Observation(code, day, said, tenor))


def _short(months: Decimal) -> bool:
    return months <= SHORT_END_MONTHS


def _long(months: Decimal) -> bool:
    return months > SHORT_END_MONTHS


def _sheets(book: zipfile.ZipFile) -> tuple[dict[str, str], date]:
    """Each sheet's path in the workbook by its name, and the workbook's
    epoch for its date serials."""
    workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
    links = ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    targets = {link.get("Id"): str(link.get("Target", "")) for link in links}
    sheets: dict[str, str] = {}
    for sheet in workbook.iter(f"{_SHEET}sheet"):
        target = targets.get(sheet.get(f"{_REL}id"), "").lstrip("/")
        sheets[str(sheet.get("name"))] = target if target.startswith("xl/") else f"xl/{target}"
    properties = workbook.find(f"{_SHEET}workbookPr")
    in_1904 = properties is not None and properties.get("date1904") in ("1", "true")
    return sheets, date(1904, 1, 1) if in_1904 else date(1899, 12, 30)


def _strings(book: zipfile.ZipFile) -> list[str]:
    try:
        shared = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in s.iter(f"{_SHEET}t")) for s in shared.iter(f"{_SHEET}si")]


def _rows(sheet: bytes, strings: list[str]) -> list[dict[str, str]]:
    """A sheet's rows, each its cells' text by column letter; an error or an
    empty cell left out."""
    rows: list[dict[str, str]] = []
    for row in ElementTree.fromstring(sheet).iter(f"{_SHEET}row"):
        cells: dict[str, str] = {}
        for cell in row.iter(f"{_SHEET}c"):
            column = "".join(ch for ch in str(cell.get("r", "")) if ch.isalpha())
            kind = cell.get("t", "n")
            if kind == "inlineStr":
                cells[column] = "".join(t.text or "" for t in cell.iter(f"{_SHEET}t"))
                continue
            value = cell.find(f"{_SHEET}v")
            if value is None or value.text is None or kind == "e":
                continue
            if kind == "s":
                at = int(value.text)
                cells[column] = strings[at] if 0 <= at < len(strings) else ""
            else:
                cells[column] = value.text
        rows.append(cells)
    return rows


def _serial(text: str, epoch: date) -> date | None:
    """An Excel date serial as a day; None where it is not one."""
    try:
        held = Decimal(text.strip())
    except InvalidOperation:
        return None
    if not held.is_finite() or held != held.to_integral_value() or not 0 < held < 2_958_466:
        return None
    return epoch + timedelta(days=int(held))
