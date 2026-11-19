# Changelog

## 0.1.1

The product owner's item 197 (2026-11-19): no third party's licensed data
in a public repository's sample recordings.

- **Sample data:** the recorded exchange rates (all 27 series, excluded
  from the Open Government Licence) and the yield curve workbooks (all four,
  their inputs Bloomberg's and Tradeweb's) hold synthetic values of the same
  shape: dates, headers, empty cells and every workbook part as received.
  SONIA, its index and Bank Rate are as received. 0.1.0's recordings stay
  in this repository's history.
- **A range wanted ends the day before its end:** the last nanosecond
  before a London midnight was read as the next day (float division), so a
  one-day range asked two; now whole seconds, as plugin-japan-mof.

## 0.1.0

On open-meridian 0.36.0, contract 30, on core aae501d's harness. The
product owner's items 128, 129, 132 and 140 (2026-11-19): Tier 1, one
plugin for the Bank's Statistical Interactive Database and its yield curve
files. The dataset keys, the records' codes and the source `boe` are
proposed here, the product owner's to approve.

- **`boe_rates`** (push and pull): SONIA, a daily `fixing` with its 10th,
  25th, 75th and 90th percentiles; the SONIA Compounded Index, an
  `index_level` based 23 April 2018 = 100; Bank Rate, a `fixing`.
  Actual/365 simple, the plugin's statement. SONIA's total nominal value is
  not carried: the database states no unit for it.
- **`boe_curves`** (pull only, served, not kept): the gilt (GLC nominal) and
  OIS spot curves, `zero` points at every whole month to five years and
  every half year beyond, continuously compounded as the Bank's yield
  curves page states; read from the latest file, or a curve's daily archive
  for an earlier day, with the standard library's zipfile and XML parser.
  No forwards (ruling 131), no real or inflation curve.
- **`boe_fx`** (pull only, served, not kept): the daily spot rates against
  sterling, each the `close` price of sterling's cash instrument in the
  other currency, never inverted.
- **Served, not kept** (ruling 132), as plugin-fred's `fred_restricted`:
  the curves' and the exchange rates' answers are never kept in the
  plugin's storage, their rows name no raw record, and each one's terms
  carry the clause for the deployment admin's licence.
- **No record minted;** no published time (the Bank states none on a value).
- **Terms in words** (`declared.BOE_TERMS`), SONIA's statement among them.
- **Pages:** the data role's Connection (with Sources) and Datasets (with
  Records).
- **Sample data:** the Bank's answers as received on 2026-11-19; the curve
  archives (some 50 MB) are not recorded.
