"""The Bank of England's series this version carries, what each one is, and
the record it is recorded against: the plugin's series map.

**Rates** (`boe_rates`, the Statistical Interactive Database, IADB). SONIA
(`IUDSOIA`), a daily `fixing` with its 10th, 25th, 75th and 90th
percentiles (`IUDZLS6` to `IUDZLS9`); the SONIA Compounded Index (`IUDZOS2`), an
`index_level` based 23 April 2018 = 100, as the Bank's SONIA key features
state it; and Bank Rate (`IUDBEDR`), a `fixing`. Each is in per cent,
actual/365, simple: the sterling money market's convention, which the
database states on none of these series -- the plugin's statement, said on
the Datasets page. SONIA's total nominal value (`IUDZLT2`) is **not
carried**: the database states no unit for it.

**Spot curves** (`boe_curves`, the yield curve files). The UK government
liability curve, nominal (the gilt curve, "GLC Nominal"), and the UK OIS
curve, each one `rate_curve` record whose points are `zero` rates at their
tenors: every whole month to five years from the file's "3. spot, short end"
sheet, then every half year beyond from its "4. spot curve" sheet, to 40
years for the gilt curve and 25 for OIS -- one grid, no tenor twice. The
values are per cent as the Bank writes them, continuously compounded: "The
yields (spot and forward) are continuously compounded and quoted on an
annual basis" (https://www.bankofengland.co.uk/statistics/yield-curves).
The forward curves and the real and inflation curves are **not carried**
(ruling 131; another curve's).

**FX** (`boe_fx`, IADB): each currency's daily spot rate against sterling,
as the Bank states it, "<currency> into sterling": units of the currency
per pound. So each is a `Price` of sterling's cash instrument in that
currency, never inverted.

Each record is asked of the deployment by its code proposed here as a
`symbol` at the source `boe`, a name **proposed** with this version for the
platform's seed; the platform seeds none yet, so until a deployment holds a
record its values wait, reported missing, never minted. Sterling is resolved
by its ISO 4217 code, as plugin-ecb resolves its currencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from meridian.operations import RateConvention
from meridian.roles.data import rates

SOURCE = "boe"
INTEREST_RATE, INDEX, RATE_CURVE = "interest_rate", "index", "rate_curve"

#: The sterling money market's convention.
MONEY_MARKET_365 = RateConvention(day_count="act_365_fixed", compounding="simple")
CONTINUOUS = rates.CONTINUOUS
SONIA_INDEX_BASE = "2018-04-23=100"

#: The IADB series read for rates.
SONIA = "IUDSOIA"
SONIA_INDEX = "IUDZOS2"
BANK_RATE = "IUDBEDR"
#: SONIA's percentiles, by the percentile each states.
PERCENTILES = {10: "IUDZLS6", 25: "IUDZLS7", 75: "IUDZLS8", 90: "IUDZLS9"}
RATE_SERIES = (SONIA, SONIA_INDEX, BANK_RATE, *PERCENTILES.values())


@dataclass(frozen=True)
class Record:
    """A referential record, by the code proposed for it at `boe`."""

    code: str
    instrument_type: str
    description: str

    @property
    def identifier(self) -> tuple[str, str, str]:
        return ("symbol", self.code, SOURCE)


SONIA_RECORD = Record("SONIA", INTEREST_RATE, "Sterling Overnight Index Average (SONIA)")
SONIA_INDEX_RECORD = Record("SONIA compounded index", INDEX, "SONIA Compounded Index")
BANK_RATE_RECORD = Record("Bank Rate", INTEREST_RATE, "Bank of England Bank Rate")
GILT_RECORD = Record(
    "Gilt nominal spot curve", RATE_CURVE, "UK government liability nominal spot curve"
)
OIS_RECORD = Record("OIS spot curve", RATE_CURVE, "UK OIS (SONIA) spot curve")
RECORDS = (SONIA_RECORD, SONIA_INDEX_RECORD, BANK_RATE_RECORD, GILT_RECORD, OIS_RECORD)
CURVE_RECORDS = (GILT_RECORD, OIS_RECORD)

#: Each rate series: its record and kind.
RATE_KINDS = {
    SONIA: (SONIA_RECORD, "fixing"),
    SONIA_INDEX: (SONIA_INDEX_RECORD, "index_level"),
    BANK_RATE: (BANK_RATE_RECORD, "fixing"),
}

#: The curve files' workbooks carried, by the start of their names in the
#: zip, and each one's record.
WORKBOOKS = {"GLC Nominal daily data": GILT_RECORD, "OIS daily data": OIS_RECORD}
SHORT_END, SPOT_CURVE = "3. spot, short end", "4. spot curve"
#: Where the short end's sheet gives way to the spot curve's: five years.
SHORT_END_MONTHS = 60
#: What the files hold and are not carried, and why.
NOT_CARRIED = {
    "GLC Real daily data": "the real curve: another curve's",
    "GLC Inflation daily data": "the implied inflation curve: another curve's",
    "1. fwds, short end": "forward rates: derived later from the spot points (ruling 131)",
    "2. fwd curve": "forward rates: derived later from the spot points (ruling 131)",
}

#: The spot rates against sterling, by IADB series: each currency's ISO 4217
#: code and name as the Bank's table names it.
FX_SERIES = {
    "XUDLADS": ("AUD", "Australian Dollar"),
    "XUDLZOS3": ("BGN", "Bulgarian Lev"),
    "XUDLCDS": ("CAD", "Canadian Dollar"),
    "XUDLBK89": ("CNY", "Chinese Yuan"),
    "XUDLBK25": ("CZK", "Czech Koruna"),
    "XUDLDKS": ("DKK", "Danish Krone"),
    "XUDLERS": ("EUR", "Euro"),
    "XUDLHDS": ("HKD", "Hong Kong Dollar"),
    "XUDLBK33": ("HUF", "Hungarian Forint"),
    "XUDLBK97": ("INR", "Indian Rupee"),
    "XUDLBK78": ("ILS", "Israeli Shekel"),
    "XUDLJYS": ("JPY", "Japanese Yen"),
    "XUDLBK83": ("MYR", "Malaysian Ringgit"),
    "XUDLNDS": ("NZD", "New Zealand Dollar"),
    "XUDLNKS": ("NOK", "Norwegian Krone"),
    "XUDLBK47": ("PLN", "Polish Zloty"),
    "XUDLZOS4": ("RON", "Romanian Leu"),
    "XUDLSRS": ("SAR", "Saudi Riyal"),
    "XUDLSGS": ("SGD", "Singapore Dollar"),
    "XUDLZRS": ("ZAR", "South African Rand"),
    "XUDLBK93": ("KRW", "South Korean Won"),
    "XUDLSKS": ("SEK", "Swedish Krona"),
    "XUDLSFS": ("CHF", "Swiss Franc"),
    "XUDLTWS": ("TWD", "Taiwan Dollar"),
    "XUDLBK87": ("THB", "Thai Baht"),
    "XUDLBK95": ("TRY", "Turkish Lira"),
    "XUDLUSS": ("USD", "US Dollar"),
}
#: The currency every rate is the price of.
STERLING = "GBP"


def tenor_of(months: Decimal | int) -> str:
    """Whole months as a tenor: 3 is 3M, 12 is 1Y, 18 is 18M."""
    whole = int(months)
    return f"{whole // 12}Y" if whole % 12 == 0 else f"{whole}M"


def months_of(stated: str, unit: str) -> Decimal | None:
    """A sheet's maturity as whole months, or None where it is not one: the
    short end states months as `1.0000000400000015`, the curve years as
    `0.5`."""
    try:
        held = Decimal(stated) * (12 if unit == "years" else 1)
    except InvalidOperation:
        return None
    if not held.is_finite():
        return None
    whole = held.to_integral_value()
    return whole if abs(held - whole) < Decimal("0.0001") and whole > 0 else None
