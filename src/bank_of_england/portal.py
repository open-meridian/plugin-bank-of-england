"""The Bank of England's website, where its Statistical Interactive Database
(IADB) and its yield curve files are served, and its stand-in.

Four kinds of request are made, and nothing else:

- SONIA, its compounded index, Bank Rate and SONIA's percentiles, for a
  range of days --
  `/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&...&SeriesCodes=IUDSOIA,...`
  with `Datefrom` and `Dateto` (`03/Aug/2026`), the database's CSV;
- the spot exchange rates against sterling, the same with their codes,
  only when the lake wants them;
- the latest yield curve file, the current month's curves, a zip --
  `/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip`,
  only when the lake wants a curve;
- a curve's daily archive (`glcnominalddata.zip`, `oisddata.zip`), for a
  day before the latest file's, only when the lake wants it.

Read from the Bank itself: no key, no account; its terms are its website's
(docs/terms.md), under which the Bank may restrict a user's access for
excessive use, and which state no figure. The plugin asks one request at a
time, at most one every two seconds, says who it is in its User-Agent, and
checks the rates' current range every hour.

`SyntheticPortal` answers from the real responses committed under
responses/ (responses/index.json), recorded on 2026-11-19: the database's
rates and exchange rates from 3 August to 19 November 2026, and the latest
yield curve file, 2 to 18 November 2026. A range is answered with the
recorded values in it, the curve file whole, and an archive not at all (it
is not recorded: some 50 MB); the rates' current range ends on its
recording's last day whatever the clock says, so the plugin's tests and its
e2e run on it, offline, the same on any day.
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import io
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from importlib import resources
from typing import Protocol

from .series import FX_SERIES, GILT_RECORD, OIS_RECORD, RATE_SERIES

BASE = "https://www.bankofengland.co.uk"
RATES, FX, CURVES = "rates", "fx", "curves"
SOURCES = (RATES, CURVES, FX)
#: The archives, by the curve record each holds.
ARCHIVE = "archive"
_IADB = (
    "/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N"
    "&SeriesCodes="
)
_CURVES = "/-/media/boe/files/statistics/yield-curves/"
#: Each source's address, before its range.
PATHS = {
    RATES: _IADB + ",".join(RATE_SERIES),
    FX: _IADB + ",".join(FX_SERIES),
    CURVES: _CURVES + "latest-yield-curve-data.zip",
}
ARCHIVES = {
    GILT_RECORD.code: _CURVES + "glcnominalddata.zip",
    OIS_RECORD.code: _CURVES + "oisddata.zip",
}
USER_AGENT = "meridian-bank-of-england (+https://github.com/open-meridian/plugin-bank-of-england)"
SPACING = 2.0
TIMEOUT = 120.0
#: The most an answer may be: the gilt curve's archive is some 40 MB.
MOST_BYTES = 64 * 1024 * 1024
#: How far the rates' current range reaches back: ten days.
CURRENT_DAYS = 10


def _iadb_day(day: date) -> str:
    return day.strftime("%d/%b/%Y")


def path_for(source: str, start: date, end: date) -> str:
    """The address of `source`'s values from `start` to `end`: the curve
    file's is the same for any range."""
    if source in (RATES, FX):
        return f"{PATHS[source]}&Datefrom={_iadb_day(start)}&Dateto={_iadb_day(end)}"
    return PATHS[source]


def source_of(path: str) -> str:
    """Which source an address asks: rates, fx, curves or archive."""
    found = next((s for s, at in PATHS.items() if path.startswith(at)), "")
    if found:
        return found
    return ARCHIVE if path in ARCHIVES.values() else ""


class PortalUnreachable(Exception):  # noqa: N818 - what the Bank's website was
    """The website could not be asked: no answer, or not in time."""


@dataclass(frozen=True)
class Fetched:
    """One answer, as received."""

    path: str
    status: int
    body: bytes
    fetched_at: datetime
    date: str = ""

    @property
    def url(self) -> str:
        return BASE + self.path

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class Portal(Protocol):
    mode: str

    def current(self, today: date) -> tuple[date, date]: ...

    async def get(self, path: str) -> Fetched: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


class LivePortal:
    """The Bank's website itself."""

    mode = "live"

    def __init__(self, now: Callable[[], datetime] = utc_now) -> None:
        self._now = now
        self._lock = asyncio.Lock()
        self._last = 0.0

    def current(self, today: date) -> tuple[date, date]:
        return today - timedelta(days=CURRENT_DAYS), today

    async def get(self, path: str) -> Fetched:
        async with self._lock:
            wait = self._last + SPACING - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                return await asyncio.to_thread(self._get, path)
            finally:
                self._last = time.monotonic()

    def _get(self, path: str) -> Fetched:
        request = urllib.request.Request(BASE + path, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:  # noqa: S310 - the Bank's https address
                body = answer.read(MOST_BYTES + 1)
                status = answer.status
                said = answer.headers
        except urllib.error.HTTPError as refused:
            body = refused.read(MOST_BYTES + 1) if refused.fp else b""
            status, said = refused.code, refused.headers
        except (urllib.error.URLError, TimeoutError, OSError) as failed:
            reason = getattr(failed, "reason", failed)
            raise PortalUnreachable(f"{BASE}{path[:80]}: {type(reason).__name__}") from failed
        if len(body) > MOST_BYTES:
            raise PortalUnreachable(f"{BASE}{path[:80]}: answered more than {MOST_BYTES} bytes")
        return Fetched(path, status, body, self._now(), date=said.get("Date", "") if said else "")


@dataclass(frozen=True)
class Recording:
    """One recorded answer, its Date and last day."""

    body: bytes
    said: str
    last_day: date


class SyntheticPortal:
    """The responses committed under responses/: each range answered with
    the recorded values in it, under its recording's Date."""

    mode = "synthetic"

    def __init__(self, now: Callable[[], datetime] = utc_now) -> None:
        self._now = now
        held = resources.files(__package__).joinpath("responses")
        index = json.loads(held.joinpath("index.json").read_text(encoding="utf-8"))
        self.recordings = {}
        for source in SOURCES:
            body = held.joinpath(index[source]["file"]).read_bytes()
            self.recordings[source] = Recording(
                gzip.decompress(body) if index[source]["file"].endswith(".gz") else body,
                str(index[source]["date"]),
                date.fromisoformat(index[source]["last_day"]),
            )
        self.asked: list[str] = []

    def current(self, today: date) -> tuple[date, date]:
        last = self.recordings[RATES].last_day
        return last - timedelta(days=CURRENT_DAYS), last

    async def get(self, path: str) -> Fetched:
        self.asked.append(path)
        source = source_of(path)
        recording = self.recordings.get(source)
        if recording is None:
            return Fetched(path, 404, b"Not found", self._now())
        if source == CURVES:
            return Fetched(path, 200, recording.body, self._now(), recording.said)
        query = dict(p.partition("=")[::2] for p in path.partition("?")[2].split("&"))
        try:
            start = datetime.strptime(query.get("Datefrom", ""), "%d/%b/%Y").date()
            end = datetime.strptime(query.get("Dateto", ""), "%d/%b/%Y").date()
        except ValueError:
            return Fetched(path, 400, b"Bad date", self._now())
        body = _within(recording.body.decode(), start, end)
        return Fetched(path, 200, body.encode(), self._now(), recording.said)


def _within(text: str, start: date, end: date) -> str:
    def inside(day: str) -> bool:
        try:
            return start <= datetime.strptime(day.strip(), "%d %b %Y").date() <= end
        except ValueError:
            return False

    rows = list(csv.reader(io.StringIO(text)))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerows([rows[0], *(r for r in rows[1:] if r and inside(r[0]))])
    return out.getvalue()


def portal(synthetic: bool, now: Callable[[], datetime] = utc_now) -> Portal:
    return SyntheticPortal(now) if synthetic else LivePortal(now)
