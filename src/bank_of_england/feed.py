"""The Bank of England's rates, curves and exchange rates into the lake:
the rates' current range recorded as the Bank publishes it, and any day of
any dataset recorded when the lake wants it (W10.4, W10.7), through the
SDK's rates helpers (`meridian.roles.data.rates`) and its `Wants`.

**Push: the rates alone.** At start and every hour, the rates' current range
-- ten days of SONIA, its compounded index and Bank Rate -- is read from the
database. An answer whose values read as the last one this process recorded
records nothing; any other is recorded whole, in the lake's batches, and the
lake answers each value it holds unchanged. A value the Bank revises within
the range is the same row key's next version.

**Pull: the curves and the exchange rates** (ruling 132, declared.py). They
are read only when the lake wants them, and their answers are never kept in
the plugin's storage: their rows name no raw record. A curve's day in the
current month is read from the latest yield curve file; an earlier one from
the curve's daily archive.

**Rows** (series.py says each): SONIA a `fixing` with its percentiles, Bank
Rate a `fixing`; the index an
`index_level`; each curve point a `zero` at its tenor on its curve's
record; each exchange rate a `close` `Price` of sterling's cash instrument
in the other currency. A value the Bank states nothing for is no row, never
a zero. Each is read from the Bank's text as a `Decimal`, never a float.

**Published time.** The Bank states none on a value: no row states one,
rather than a wrong one.

**Subjects.** Each record by its code at `boe` (series.py), sterling by its
ISO 4217 code, resolved once per process, at its first check; one the
deployment does not hold is reported missing, and its values wait. The
plugin mints nothing.

**Wants.** A want of one of the three datasets, for subjects the plugin
records -- a business date, a range of at most a year, or the latest -- is
read from the Bank and recorded against the want; a day the Bank states
nothing for, or one not come yet, is declined `source_silent`; any other
subject, or another kind of data, `not_covered`.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import meridian
from meridian.operations import Money, ObservationMeta, Price, SubjectRef
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles import data
from meridian.roles.data import rates

from .answers import NotRead, Observations, parse_curves, parse_iadb
from .declared import BOE_CURVES, BOE_FX, BOE_RATES, DAY_TIME_ZONE, KEYS, PRICE, RATE
from .portal import (
    ARCHIVES,
    CURVES,
    FX,
    RATES,
    SOURCES,
    Fetched,
    Portal,
    PortalUnreachable,
    path_for,
    utc_now,
)
from .raw import RawStore
from .series import (
    CONTINUOUS,
    CURVE_RECORDS,
    FX_SERIES,
    MONEY_MARKET_365,
    PERCENTILES,
    RATE_KINDS,
    SONIA,
    SONIA_INDEX_BASE,
    SOURCE,
    STERLING,
    Record,
)

log = logging.getLogger("bank_of_england")

LONDON = ZoneInfo(DAY_TIME_ZONE)
#: Each source's dataset, and back.
DATASETS = {RATES: BOE_RATES, CURVES: BOE_CURVES, FX: BOE_FX}
SOURCES_OF = {BOE_RATES: RATES, BOE_CURVES: CURVES, BOE_FX: FX}
#: The sources read only when wanted, their answers never kept.
PULLED = (CURVES, FX)
#: The most days one want is answered for: a year.
MOST_DAYS = 366
#: How far back "the latest" is looked for, for a source read only when wanted.
LATEST_DAYS = 10


def _ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000) * 1000


def day_bounds(day: date) -> tuple[int, int]:
    start = datetime.combine(day, time(0, 0), LONDON)
    return _ns(start), _ns(datetime.combine(day + timedelta(days=1), time(0, 0), LONDON))


@dataclass(frozen=True)
class Outcome:
    recorded: int = 0
    restated: int = 0
    unchanged: int = 0
    unresolved: tuple[str, ...] = ()


@dataclass
class Held:
    """A record or a currency as the plugin last saw it: the deployment's
    instrument, or why there is none, and the latest day recorded."""

    code: str
    name: str = ""
    instrument_id: str = ""
    miss: str = ""
    latest_day: date | None = None


@dataclass
class SourceStatus:
    """What the plugin last did with one source, for its pages."""

    source: str
    checked_at: datetime | None = None
    read_at: datetime | None = None
    error: str = ""
    first_day: date | None = None
    latest_day: date | None = None
    fetches: int = 0
    unread: dict[str, int] = field(default_factory=dict)


@dataclass
class Status:
    """What the plugin last did, for its pages; lost on a restart."""

    mode: str = "live"
    started_at: datetime | None = None
    sources: dict[str, SourceStatus] = field(
        default_factory=lambda: {s: SourceStatus(s) for s in SOURCES}
    )
    records: dict[str, Held] = field(default_factory=dict)
    sterling: Held = field(default_factory=lambda: Held(STERLING, "Pound sterling"))
    #: Each exchange rate's latest day recorded, by its currency's ISO code.
    fx_days: dict[str, date] = field(default_factory=dict)

    @property
    def checked_at(self) -> datetime | None:
        stamps = [s.checked_at for s in self.sources.values() if s.checked_at]
        return max(stamps) if stamps else None

    @property
    def error(self) -> str:
        return next((s.error for s in self.sources.values() if s.error), "")

    @property
    def fetches(self) -> int:
        return sum(s.fetches for s in self.sources.values())

    @property
    def read(self) -> bool:
        return any(s.read_at for s in self.sources.values())


class Feed(data.Role):
    """The plugin's data role class, its acts made on itself -- registered
    with `meridian.run`, or bound to the suite's recorder in its tests."""

    def __init__(
        self, portal: Portal, raw: RawStore, now: Callable[[], datetime] = utc_now
    ) -> None:
        self.portal = portal
        self.raw = raw
        self.now = now
        self.wants = data.Wants(self, KEYS, clock_ns=lambda: _ns(self.now()))
        self.rates = rates.Feed(
            self, SOURCE, wants=self.wants, day_zone=DAY_TIME_ZONE, clock_ns=lambda: _ns(self.now())
        )
        self.status = Status(mode=portal.mode, started_at=now())
        self._recorded: dict[str, str] = {}

    def today(self) -> date:
        return self.now().astimezone(LONDON).date()

    def use(self, portal: Portal) -> None:
        """Read from `portal` from now on: sample data turned on or off."""
        if portal.mode != self.portal.mode:
            self.portal = portal
            self.status.mode = portal.mode
            self._recorded.clear()

    # ── Reading ─────────────────────────────────────────────────────────

    async def _get(self, source: str, path: str) -> Fetched:
        held = self.status.sources[source]
        fetched = await self.portal.get(path)
        held.fetches += 1
        return fetched

    async def read(self, source: str, start: date, end: date) -> tuple[Observations, str]:
        """`source`'s values from `start` to `end`, and the answer's key in
        storage: empty for a source never kept. PortalUnreachable or NotRead
        otherwise."""
        fetched = await self._get(source, path_for(source, start, end))
        key = self.raw.keep(fetched) if source not in PULLED else ""
        if fetched.status != 200:
            raise PortalUnreachable(f"{fetched.url[:120]} answered {fetched.status}")
        if source == CURVES:
            read = parse_curves(fetched.body, source, start, end)
            first = read.days[0] if read.days else end + timedelta(days=1)
            if start < first:
                await self._archives(read, start, min(end, first - timedelta(days=1)))
        else:
            read = parse_iadb(fetched.text, source)
        held = self.status.sources[source]
        for line in read.unread:
            held.unread[line] = held.unread.get(line, 0) + 1
        return read, key

    async def _archives(self, read: Observations, start: date, end: date) -> None:
        """The days before the latest curve file's, from each curve's daily
        archive, into `read`; an archive not answering adds nothing."""
        for code, path in ARCHIVES.items():
            fetched = await self._get(CURVES, path)
            if fetched.status != 200:
                log.warning("%s's archive answered %s", code, fetched.status)
                continue
            older = parse_curves(fetched.body, CURVES, start, end)
            read.observations += [o for o in older.observations if o.series == code]
            read.unread += older.unread

    # ── Resolving ───────────────────────────────────────────────────────

    async def record_of(self, record: Record) -> str:
        """A record's instrument, by its code at `boe`; empty, reported
        missing, where the deployment holds none."""
        held = self.status.records.setdefault(record.code, Held(record.code, record.description))
        if held.instrument_id:
            return held.instrument_id
        found = await self.rates.subject(
            record.identifier,
            description=record.description,
            instrument_type=record.instrument_type,
        )
        held.instrument_id, held.miss = found, "" if found else "not held: reported missing"
        return found

    async def sterling(self) -> str:
        """Sterling's cash instrument by ISO 4217, resolved now where not
        yet; empty, reported missing with why, where none resolves."""
        held = self.status.sterling
        if held.instrument_id:
            return held.instrument_id
        identifier = ops.Identifier(scheme="iso4217", value=STERLING)
        found = await self.resolve_identifier(
            identifiers=[identifier],
            as_of_ns=_ns(self.now()),
            stated_asset_class="cash",
            stated_currency=STERLING,
            stated_description=f"{STERLING} cash",
        )
        if found.found and found.instrument_id:
            held.instrument_id, held.miss = found.instrument_id, ""
            return str(found.instrument_id)
        if held.miss:
            return ""
        reason = found.miss_reason or ops.MISS_REASON_NOT_FOUND
        held.miss = ops.MissReason.Name(reason).removeprefix("MISS_REASON_").lower()
        await self.report_missing_instrument(
            source=SOURCE,
            asset_class="cash",
            identifiers=[identifier],
            reason=reason,
            as_of_ns=_ns(self.now()),
            observed_at_ns=_ns(self.now()),
        )
        return ""

    async def resolve_pulled(self) -> None:
        """The subjects of the datasets read only when wanted, resolved so a
        want can name them: each curve's record, and sterling."""
        for record in CURVE_RECORDS:
            await self.record_of(record)
        await self.sterling()

    # ── Recording ───────────────────────────────────────────────────────

    def _first(self, name: str, day: date, key: str) -> str:
        return self.raw.noted(name, day, key)[0].key

    def _note(self, held: Held, day: date) -> None:
        if held.latest_day is None or day > held.latest_day:
            held.latest_day = day

    async def _rate_rows(self, read: Observations, key: str, days: set[date] | None) -> list[Any]:
        rows: list[Any] = []
        for seen in read.observations:
            if days is not None and seen.day not in days:
                continue
            record, kind = RATE_KINDS.get(seen.series, (None, ""))
            if record is None:
                continue
            subject = await self.record_of(record)
            if not subject:
                continue
            said, percentiles = seen.text, None
            if seen.series == SONIA:
                stated = read.on(seen.day)
                percentiles = {p: stated[s].text for p, s in PERCENTILES.items() if s in stated}
                said += "|" + "|".join(f"{p}:{v}" for p, v in sorted(percentiles.items()))
            value = (
                rates.index_level(seen.text, SONIA_INDEX_BASE)
                if kind == "index_level"
                else rates.percent(seen.text)
            )
            rows.append(
                self.rates.rate(
                    subject,
                    BOE_RATES,
                    kind,
                    value,
                    business_date=seen.day,
                    convention=MONEY_MARKET_365,
                    series=seen.series,
                    raw_key=self._first(f"{seen.series}:{seen.day}={said}", seen.day, key),
                    percentiles=percentiles or None,
                )
            )
            self._note(self.status.records[record.code], seen.day)
        return rows

    async def _curve_rows(self, read: Observations, days: set[date] | None) -> list[Any]:
        rows: list[Any] = []
        by_code = {r.code: r for r in CURVE_RECORDS}
        for seen in read.observations:
            record = by_code.get(seen.series)
            if record is None or (days is not None and seen.day not in days):
                continue
            subject = await self.record_of(record)
            if not subject:
                continue
            rows.append(
                self.rates.rate(
                    subject,
                    BOE_CURVES,
                    "zero",
                    rates.percent(seen.text),
                    business_date=seen.day,
                    convention=CONTINUOUS,
                    tenor=seen.tenor,
                    series=record.code,
                )
            )
            self._note(self.status.records[record.code], seen.day)
        return rows

    async def _prices(self, read: Observations, days: set[date] | None) -> list[Any]:
        prices: list[Any] = []
        subject = await self.sterling()
        if not subject:
            return prices
        dataset = self.wants.dataset(BOE_FX)
        for seen in read.observations:
            code = FX_SERIES.get(seen.series, ("", ""))[0]
            if not code or (days is not None and seen.day not in days):
                continue
            start, end = day_bounds(seen.day)
            prices.append(
                Price(
                    meta=ObservationMeta(
                        row_key=f"{STERLING}{code}:{seen.day.isoformat()}",
                        subjects=[SubjectRef(entity_id=subject)],
                        source=ops.Source(dataset=dataset),
                        valid_from_ns=start,
                        valid_until_ns=end,
                        business_date=seen.day.isoformat(),
                    ),
                    kind="close",
                    price=Money(seen.value, code),
                    basis="per_unit",
                )
            )
            held = self.status.fx_days.get(code)
            self.status.fx_days[code] = max(held, seen.day) if held else seen.day
            self._note(self.status.sterling, seen.day)
        return prices

    async def record(
        self,
        read: Observations,
        key: str,
        *,
        want_id: str = "",
        days: Iterable[date] | None = None,
        subjects: set[str] | None = None,
    ) -> tuple[Outcome, set[str]]:
        """Record `read` -- on `days` and for `subjects` where given --
        against `want_id` where given. What the lake answered, and the
        subjects a row was sent for."""
        source = read.source
        dataset = DATASETS[source]
        wanted = set(days) if days is not None else None
        rows: list[Any]
        if source == FX:
            rows = await self._prices(read, wanted)
        elif source == RATES:
            rows = await self._rate_rows(read, key, wanted)
        else:
            rows = await self._curve_rows(read, wanted)
        if subjects is not None:
            rows = [r for r in rows if r.meta.subjects[0].entity_id in subjects]
        if source == FX:
            unresolved = [STERLING] if self.status.sterling.miss else []
        else:
            unresolved = [h.code for h in self.status.records.values() if h.miss]
        self.raw.save_firsts()
        counts = self.wants.sent_to(dataset)
        before = (counts.recorded, counts.restated, counts.unchanged)
        if source == FX:
            await self.wants.record("prices", rows, dataset, want_id)
        else:
            await self.rates.record(dataset, rows, want_id)
        sent = {r.meta.subjects[0].entity_id for r in rows}
        outcome = Outcome(
            counts.recorded - before[0],
            counts.restated - before[1],
            counts.unchanged - before[2],
            tuple(unresolved),
        )
        return outcome, sent

    async def check(self) -> dict[str, Outcome]:
        """Read the rates' current range and record it where this process
        has not recorded it as it reads now; resolve the subjects of the
        datasets read only when wanted."""
        done: dict[str, Outcome] = {}
        held = self.status.sources[RATES]
        held.checked_at = self.now()
        start, end = self.portal.current(self.today())
        try:
            read, key = await self.read(RATES, start, end)
        except (PortalUnreachable, NotRead) as failed:
            held.error = str(failed)
            log.warning("the rates were not read: %s", failed)
            return done
        held.error = ""
        held.read_at = self.now()
        if read.days:
            held.first_day, held.latest_day = read.days[0], read.days[-1]
        await self.resolve_pulled()
        digest = digest_of(read)
        if digest == self._recorded.get(RATES):
            return done
        outcome, _ = await self.record(read, key)
        done[RATES] = outcome
        if not outcome.unresolved:
            self._recorded[RATES] = digest
        log.info(
            "rates of %s to %s: %d recorded, %d restated, %d unchanged%s",
            held.first_day,
            held.latest_day,
            outcome.recorded,
            outcome.restated,
            outcome.unchanged,
            f"; not held: {', '.join(outcome.unresolved)}" if outcome.unresolved else "",
        )
        return done

    # ── Wants ───────────────────────────────────────────────────────────

    async def on_observations_wanted(
        self, heard: meridian.Heard[ops.ObservationsWantedEvent]
    ) -> None:
        await self.wants.hear(heard, self.answer)

    async def on_want_withdrawn(self, heard: meridian.Heard[ops.WantWithdrawnEvent]) -> None:
        self.wants.withdraw(heard.message.want_id)
        log.info("standing want %s withdrawn", heard.message.want_id)

    def _days(self, source: str, want: ops.ObservationsWantedEvent) -> tuple[list[date], bool]:
        """The days a want asks, and whether it asks only the latest."""
        if want.business_date:
            return [date.fromisoformat(want.business_date)], False
        if want.valid_from_ns or want.valid_until_ns:
            # Whole seconds, so the last nanosecond before a midnight is
            # that day's, never rounded into the next.
            start = datetime.fromtimestamp(want.valid_from_ns // 10**9, LONDON).date()
            until = want.valid_until_ns - 1 if want.valid_until_ns else _ns(self.now())
            end = datetime.fromtimestamp(until // 10**9, LONDON).date()
            return [start + timedelta(days=n) for n in range((end - start).days + 1)][
                -MOST_DAYS:
            ], False
        latest = self.status.sources[source].latest_day
        if latest and source == RATES:
            return [latest], True
        today = self.today()
        return [today - timedelta(days=n) for n in range(LATEST_DAYS, -1, -1)], True

    def _held(self, source: str) -> set[str]:
        if source == FX:
            return {self.status.sterling.instrument_id} - {""}
        codes = (
            [r.code for r in CURVE_RECORDS]
            if source == CURVES
            else [r.code for r, _ in RATE_KINDS.values()]
        )
        return {
            h.instrument_id
            for c, h in self.status.records.items()
            if c in codes and h.instrument_id
        }

    async def answer(
        self,
        want: ops.ObservationsWantedEvent,
        key: str,
        subjects: list[str],
        kinds: tuple[int, ...],
    ) -> dict[str, str]:
        """One want answered from the Bank: its values recorded against it,
        and each subject declined, with why."""
        source = SOURCES_OF.get(key, "")
        serves = PRICE if key == BOE_FX else RATE
        if not source or want.data_type not in ("", serves):
            return {s: "not_covered" for s in subjects}
        if key == BOE_FX and kinds and ops.PRICE_KIND_CLOSE not in kinds:
            return {s: "not_covered" for s in subjects}
        if source in PULLED:
            await self.resolve_pulled()
        held = self._held(source)
        declined = {s: "not_covered" for s in subjects if s not in held}
        asked = [s for s in subjects if s in held]
        if not asked:
            return declined
        if want.standing:
            self.wants.stand(want, asked, kinds)
        days, latest = self._days(source, want)
        days = [d for d in days if d <= self.today()]
        sent: set[str] = set()
        if days:
            status = self.status.sources[source]
            status.checked_at = self.now()
            try:
                read, raw_key = await self.read(source, min(days), max(days))
                status.error, status.read_at = "", self.now()
                if read.days:
                    status.first_day = min(read.days[0], status.first_day or read.days[0])
                    status.latest_day = max(read.days[-1], status.latest_day or read.days[-1])
                if latest:
                    days = read.days[-1:]
                _, sent = await self.record(
                    read, raw_key, want_id=want.want_id, days=days, subjects=set(asked)
                )
            except (PortalUnreachable, NotRead) as failed:
                status.error = str(failed)
                log.warning("want %s: %s was not read: %s", want.want_id, source, failed)
        for subject in asked:
            if subject not in sent:
                declined[subject] = "source_silent"
        return declined


def digest_of(read: Observations) -> str:
    """What an answer states, as a short digest: its values alone."""
    stated = repr([(o.series, o.day, o.text) for o in read.observations]).encode()
    return hashlib.sha256(stated).hexdigest()[:16]
