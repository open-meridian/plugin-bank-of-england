"""What this version declares beside its role, `data` (W8.1, W4.1; the
catalogue from contract v18), built from code and used twice: `__main__`
registers with it, and `meridian plugin upload` reads it from the built image
(pyproject.toml's `[tool.meridian] declaration`).

**The catalogue: three datasets** (the product owner, items 128, 129, 132
and 140, 2026-11-19: Tier 1, one plugin for the Bank's two feeds; their keys
proposed, the product owner's to approve):

- **`boe_rates`**: SONIA with its percentiles, the SONIA Compounded Index
  and Bank Rate -- rates,
  daily, from the database; pushed as the Bank publishes them and any past
  day pulled when the lake wants it;
- **`boe_curves`**: the gilt (nominal government liability) and OIS spot
  curves, `zero` rates at each tenor on each curve's record, daily, from
  the yield curve files -- rates;
- **`boe_fx`**: the spot exchange rates against sterling, each the price of
  sterling's cash instrument in the other currency -- prices, daily, from
  the database.

**Served, not kept** (ruling 132, as plugin-fred's `fred_restricted` and
plugin-ecb's `ecb_yc` say it). The Bank reproduces its exchange rates under
licence from third parties, outside the Open Government Licence, and names
its curves' inputs as Bloomberg's and Tradeweb's. So `boe_curves` and
`boe_fx` are pulled only, never pushed, and their answers are never kept in
the plugin's storage; the rows the lake receives are recorded as any are.
Whether a deployment keeps them is its licence: "served, not kept" is the
default the clause in each one's terms asks the deployment admin to set
(ruling 1032 retired `licence_default`, so the plugin declares none).

Each: `vendor` the Bank of England, no aggregator; `cadence` a day; its day
London's (the Bank's business day), ending at midnight; no calendar (the
platform holds none for sterling yet); no venue; `history` 0, as each
series states; its terms and pricing (contract 30, ruling 1032) the Bank's,
in plain words, and no licence declared -- a deployment's licence, set on
the Data sources page, is the one enforced; a gap asked again
(`gap_recovery` `backfill`, W10.14).

**Storage:** the rates' answers (raw.py), archivable, ten years by default.
"""

from __future__ import annotations

from meridian import DatasetDeclaration
from meridian.declaration import RecordKind

from .raw import DEFAULT_WINDOW_DAYS, RESPONSES

BOE_RATES, BOE_CURVES, BOE_FX = "boe_rates", "boe_curves", "boe_fx"
KEYS = (BOE_RATES, BOE_CURVES, BOE_FX)
#: The datasets served when wanted and never kept here (ruling 132).
NOT_KEPT = (BOE_CURVES, BOE_FX)
VENDOR = "Bank of England"
RATE = "meridian.v1.Rate"
PRICE = "meridian.v1.Price"
CADENCE = 86_400
DAY_TIME_ZONE = "Europe/London"
DAY_END_MINUTE = 0

#: The Bank's terms, in plain words (contract 30, ruling 1032), from its
#: legal page (https://www.bankofengland.co.uk/legal) and its yield curves'
#: page (https://www.bankofengland.co.uk/statistics/yield-curves), read on
#: 2026-11-19.
BOE_TERMS = (
    "The Bank of England's website and its Statistical Interactive Database: free, no key or "
    "account. The Database's data are the copyright of the Governor and Company of the Bank of "
    "England; reproducing them is subject to the UK Open Government Licence. The Bank may "
    "restrict a user's access for excessive use."
)
#: The clause each restricted dataset records for its deployment admin.
NOT_KEPT_CLAUSE = (
    " Its licence default is served, not kept (ruling 132): the plugin pulls it only when "
    "wanted and keeps none of its answers; whether the lake keeps its rows is the deployment "
    "admin's licence to set."
)
TERMS = {
    BOE_RATES: BOE_TERMS
    + (
        " SONIA and/or SONIA Compounded Index data licensed under the Open Government Licence "
        "v3.0 and copyright the Governor and Company of the Bank of England. The trade marks "
        '"Bank of England" and "SONIA" are registered trade marks of the Bank of England. '
        "SONIA is administered by the Bank of England."
    ),
    BOE_CURVES: BOE_TERMS
    + (
        " The yield curves are the Bank's estimates; their sources are Bloomberg Finance L.P., "
        "Tradeweb (the gilt curve) and Bank calculations. The Bank sees no objection to their "
        "electronic storage used under its copyright and disclaimer terms; they are revised, "
        "and the latest are on its website. This dataset carries each curve's spot rates; its "
        "forward rates are not carried."
    )
    + NOT_KEPT_CLAUSE,
    BOE_FX: BOE_TERMS
    + (
        " Selected exchange rate data and series are excluded from the Open Government "
        "Licence, reproduced by the Bank under licence from third parties (LSEG's); the Bank "
        "states its rates are not official rates. Using them beyond that needs the owner's "
        "permission."
    )
    + NOT_KEPT_CLAUSE,
}


def _dataset(key: str, data_types: list[str], modes: list[str]) -> DatasetDeclaration:
    return DatasetDeclaration(
        key=key,
        vendor=VENDOR,
        data_types=data_types,
        modes=modes,
        cadence=CADENCE,
        history=0,
        terms_and_pricing=TERMS[key],
        gap_recovery="backfill",
        day_time_zone=DAY_TIME_ZONE,
        day_end_minute=DAY_END_MINUTE,
    )


CATALOGUE = [
    _dataset(BOE_RATES, [RATE, "meridian.v1.Rate.percentiles"], ["push", "pull"]),
    _dataset(BOE_CURVES, [RATE], ["pull"]),
    _dataset(BOE_FX, [PRICE], ["pull"]),
]

RESPONSES_KIND = RecordKind(RESPONSES, "Raw responses", window_days=DEFAULT_WINDOW_DAYS)
