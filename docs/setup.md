# Setup

## Launching it

The Bank's data need no key and no account. Launch the plugin and approve its
one role, `data`. It reads the Bank's rates at once, and every hour after; the curves and
the exchange rates only when the lake asks for a day.

Its settings: the **Raw responses window** and **past the window** (the
SDK's), and on a deployment installed for development, **Sample data**: the
Bank's answers recorded on 19 November 2026, committed with the plugin.

## Its datasets

On the deployment's **Data sources** page (deployment admins), for each of
`<instance>:boe_rates`, `<instance>:boe_curves` and `<instance>:boe_fx`:

1. **License it.** Each dataset describes the Bank's terms in words and
   declares no licence ([terms](terms.md)). `boe_rates` is under the Open
   Government Licence, with SONIA's statement. `boe_curves` and `boe_fx`
   carry the clause "served, not kept": the Bank's exchange rates are
   reproduced under third parties' licence, and its curves' inputs are
   Bloomberg's and Tradeweb's, so the plugin reads them only when wanted and
   keeps none of their answers; set their licence not to keep them unless
   your terms with those parties allow it. Until a licence is set, the lake
   keeps the rows and reads every use right restrictively.
2. **Entitle** each plugin that reads it.
3. **Priority**, where another dataset states the same values.

## The records

SONIA, its index, Bank Rate and the two curves are each about a record
named by a code at `boe`: `boe:SONIA`, `boe:SONIA compounded index`,
`boe:Bank Rate`, `boe:Gilt nominal spot curve`, `boe:OIS spot curve`. The
platform does not seed them yet, and the plugin never makes one: the
Datasets page's Records tab shows each as not held, and its values wait
until your deployment holds it. Sterling is found by its ISO 4217 code.
