# Overview

The Bank of England publishes the rates this plugin puts into your
deployment's lake:

- **SONIA, its compounded index and Bank Rate** (`<instance>:boe_rates`):
  SONIA each business day, with its 10th, 25th, 75th and 90th percentiles;
  the SONIA Compounded Index, based 23 April 2018 = 100; and Bank Rate.
- **Spot curves** (`<instance>:boe_curves`): the gilt (nominal government
  liability) and OIS spot curves, each at every whole month to five years
  and every half year beyond, to 40 years (gilt) or 25 (OIS).
- **Exchange rates** (`<instance>:boe_fx`): each currency's daily spot rate
  against sterling, the price of one pound in that currency.

It reads the Bank's public website: no key, no account. It checks for new
rates every hour. The curves and the exchange rates are read only when your
lake asks for a day (served, not kept: [terms](terms.md)); any past day of
any dataset is read when the lake asks for it.

## What it records

- **Each value as the Bank writes it,** made an exact decimal from its text.
  A day the Bank states nothing for is no value, never a zero.
- **Conventions.** The database states its rates in per cent and no day
  count; the plugin states SONIA, its index and Bank Rate actual/365 simple
  (the sterling money market's). The curves are continuously compounded,
  quoted on an annual basis, as the Bank's yield curves page states.
- **Against your deployment's records.** SONIA, its index, Bank Rate and the
  two curves are each asked of your deployment by a code at `boe`; the
  plugin never makes a record: one your deployment does not hold is reported
  missing, and its values wait. Sterling is found by its ISO 4217 code.
- **No published time:** the Bank states none on a value.
- **Not carried:** SONIA's total nominal value (the database states no unit
  for it), the forward curves, and the real and inflation curves.

## What it never does

It records no trade and shows no value on its pages. It holds no account and
uses no key. Its exchange rates are never inverted, and it keeps no answer
of the curves' or the exchange rates'.
