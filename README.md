# meridian-bank-of-england

The Bank of England's public rates for [Open Meridian](https://open-meridian.com):
an Open Meridian plugin that puts SONIA, its compounded index and Bank Rate,
the Bank's gilt and OIS spot curves, and its daily spot exchange rates
against sterling into a deployment's lake. It reads the Bank's Statistical
Interactive Database and its yield curve files, and holds the `data` role, a
data plugin. This is release 0.1.1, a draft for the product owner. How to
set it up and use it is in [docs/](docs/README.md).

It is built on the SDK it pins, `open-meridian==0.37.0` (contract 30).

## What it records

- **`<instance>:boe_rates`** (pushed as published, and pulled): SONIA, each
  day's `fixing` with its 10th, 25th, 75th and 90th percentiles; the SONIA
  Compounded Index, an index level based 23 April 2018 = 100; Bank Rate, a
  `fixing`. In per cent, actual/365 simple: the sterling money market's
  convention, the plugin's statement, since the database states only per
  cent.
- **`<instance>:boe_curves`** (pulled only, served, not kept): the gilt
  (nominal government liability) and OIS spot curves, each a curve record's
  zero rates at every whole month to five years, then every half year to 40
  years (gilt) or 25 (OIS), in per cent as the Bank writes them,
  continuously compounded, as the Bank's yield curves page states. A day in
  the current month is read from the latest file, an earlier one from the
  curve's daily archive. No forward rates; no real or inflation curve.
- **`<instance>:boe_fx`** (pulled only, served, not kept): each currency's
  daily spot rate against sterling, the price of sterling's cash instrument
  in that currency, as the Bank states it, never inverted.
- **Records:** SONIA, its index, Bank Rate and the two curves are each asked
  of the deployment by a code at `boe` (`boe:SONIA`); the platform seeds
  none yet, so each is reported missing, never minted, and its rates wait.
  Sterling resolves by its ISO 4217 code.
- **Not presented:** SONIA's total nominal value (the database states no
  unit for it); the forward, real and inflation curves. No published time
  is recorded: the Bank states none.

## Served, not kept

The Bank reproduces its exchange rates under licence from third parties,
outside the Open Government Licence, and names its curves' inputs as
Bloomberg's and Tradeweb's. So `boe_curves` and `boe_fx` are read only when
the lake wants a day, and the plugin keeps none of their answers. Each
dataset's terms carry the clause for the deployment admin, whose licence
says whether the lake keeps their rows: "served, not kept" is the default
the clause asks for.

## Deploying it

On a deployment, with the `meridian` CLI connected (`meridian connect`):

    meridian plugin upload                   # from this directory
    meridian plugin launch bank-of-england   # a deployment admin approves its one role, data

No key and no account. A deployment admin then licenses its three datasets
and entitles the plugins that read them on the Data sources page
([docs/setup.md](docs/setup.md)).

## Checking it

    make ci-local                  # lint, tests, plugin check, image, e2e: the pre-push gate
    make preview SHOTS=<dir>       # each page in a browser with the kit, at 375, 582 and 1280 px

`tests/test_suite.py` runs the SDK's data suite on the plugin's own
conversion, and it passes; a case about what the Bank never states here is
not presented, with why.

## The terms, summarised

Not legal advice; read the Bank's own words
([legal](https://www.bankofengland.co.uk/legal),
[yield curves](https://www.bankofengland.co.uk/statistics/yield-curves))
before relying on them. The Database's data are the Bank's copyright, and
reproducing them is subject to the UK Open Government Licence; SONIA and/or
SONIA Compounded Index data licensed under the Open Government Licence v3.0
and copyright the Governor and Company of the Bank of England; selected
exchange rate data are excluded from that licence; the curves' sources are
Bloomberg Finance L.P., Tradeweb and Bank calculations; the Bank may
restrict access for excessive use. Each dataset says so in words, and
declares no licence: the deployment admin's licence is the one enforced.
This project is not affiliated with or endorsed by the Bank of England.

## Licence

Apache-2.0 (LICENSE, NOTICE). The Bank's answers under
`src/bank_of_england/responses/` were recorded on 2026-11-19: the rates as
received; the exchange rates and the yield curves (third parties' data
under ruling 132) synthetic.
