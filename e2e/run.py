"""`make e2e`: the plugin on the plugin harness of the runtime it pins
(contract 30), beside `reader`, a reporting plugin (e2e/reader.py), and the
harness's admin. Run from the repository's root by the Makefile; standard
library only.

1. The website unreachable: the plugin's hosts file sends the Bank's website
   nowhere, so its first check fails, and Connection says "Not answering"
   and records nothing.
2. Sample data on: the plugin reads the committed answers; each of the five
   records (SONIA, its index, Bank Rate, the gilt and OIS curves) is asked
   of the deployment by its code at `boe` and, since the platform seeds none
   yet, reported missing, never minted, its rates waiting; sterling
   resolves to its cash instrument by ISO 4217 code. Nothing is pushed but
   the rates, so the lake holds no row.
3. Parity: `read_connection` and `read_datasets` answer what the pages show,
   and core's `dashboard__list_datasets` lists the three datasets as
   declared: the rates pushed and pulled, the curves and the exchange rates
   pulled only.
4. Licensed (the rates kept; the curves and the exchange rates served, not
   kept, ruling 132) and entitled; the reader asks for sterling's prices of
   18 November 2026, the lake wants them of the plugin, and the plugin
   reads them from the Bank and records them against the want.
5. `store lake` is e2e/expected.lake, sterling's instrument named GBP.
6. A new container records nothing twice, reports each record missing again,
   and reads its licences on start.
"""

import json
import os
import subprocess
import sys
import time

PROJECT = "boe-e2e"
LOG = ".e2e/runner.log"
COMPONENTS = ".e2e/components.log"
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", ".e2e/harness/compose.yaml",
           "-f", ".e2e/harness/plugins.yaml", "-f", "e2e/plugin.yaml"]
INSTANCE = "bank-of-england"
DATASETS = {f"{INSTANCE}:{k}": k for k in ("boe_rates", "boe_curves", "boe_fx")}
FX = f"{INSTANCE}:boe_fx"
#: The datasets served, not kept (ruling 132).
NOT_KEPT = (f"{INSTANCE}:boe_curves", FX)
#: The five records, each reported missing once a process.
MISSES = 5


class Failed(Exception):
    pass


def log(text):
    with open(LOG, "a", encoding="utf-8") as kept:
        kept.write(text + "\n")


def compose(*args, check=True, timeout=600):
    done = subprocess.run(COMPOSE + list(args), capture_output=True, text=True,
                          timeout=timeout)
    log(f"$ compose {' '.join(args)[:300]}\n{done.stdout[-4000:]}{done.stderr[-2000:]}")
    if check and done.returncode != 0:
        raise Failed(f"compose {' '.join(args)[:200]}: {(done.stdout + done.stderr).strip()[-600:]}")
    return done


def runner(*args, check=True):
    done = compose("run", "--rm", "-T", "runner", *args, check=check)
    return done.stdout if check else done


def must(condition, why):
    if not condition:
        raise Failed(why)


def until(seconds, attempt, what):
    deadline = time.monotonic() + seconds
    last = None
    while True:
        try:
            answer = attempt()
        except Failed as failed:
            answer, last = None, failed
        if answer:
            return answer
        if time.monotonic() > deadline:
            raise Failed(f"{what}, in {seconds} seconds" + (f": {last}" if last else ""))
        time.sleep(2)


def page(instance, level, path):
    said = runner("page", "--instance", instance, "--level", level, path)
    status, _, body = said.partition("\n")
    must(status.strip() == "200", f"{instance} {path} answered {said[-600:]}")
    return body


def call(tool, arguments=None):
    done = runner("mcp", "call", tool, json.dumps(arguments or {}), check=False)
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        raise Failed(f"{tool}: no answer: {(done.stdout + done.stderr)[-400:]}")
    must(answer.get("outcome") in ("read", "unchanged"), f"{tool} answered {done.stdout[-700:]}")
    return answer["data"]


def store_lake():
    return compose("run", "--rm", "-T", "store", "lake").stdout


def named(lines, codes):
    """`store lake` with each instrument's ID, drawn per run, as its code."""
    out = []
    for line in lines.strip().splitlines():
        parts = line.split("|")
        if parts[0] == "row" and len(parts) > 6:
            parts[6] = codes.get(parts[6], parts[6])
        elif parts[0] == "want" and len(parts) > 3:
            parts[3] = ",".join(codes.get(s, s) for s in parts[3].split(","))
        out.append("|".join(parts))
    return "\n".join(sorted(out)) + "\n"


def run():
    started = time.time()
    compose("--profile", "runner", "down", "-v", "--remove-orphans", check=False)
    compose("up", "-d")
    runner("ready")
    runner("ready", "--instance", "reader")

    # 1. The website unreachable.
    page_said = runner("page", "--level", "admin", "/", "--until", "Not answering",
                       "--seconds", "90")
    must("Error" in page_said, f"step 1, Connection names why the Bank was not reached: {page_said[-500:]}")
    must("row|" not in store_lake(), "step 1, nothing recorded with the website unreachable")

    # 2. Sample data.
    runner("settings", "sample_data=true")
    runner("page", "--level", "admin", "/datasets?tab=records", "--until", 'data-code="USD"',
           "--seconds", "120")
    runner("page", "--level", "admin", "/?tab=sources", "--until", "Wed 18 Nov 2026",
           "--seconds", "60")
    until(90, lambda: f"miss|{INSTANCE}|{MISSES}" in store_lake(),
          f"step 2, the {MISSES} records were not reported missing")
    must("row|" not in store_lake(), "step 2, no row: the rates wait, the rest are pulled only")

    # 3. Parity through the deployment's MCP, and core's view of the catalogue.
    runner("grant", "--level", "admin")
    runner("mcp", "connect", "--covers", "deployment_admin", "--covers", f"{INSTANCE}:admin")
    tools = runner("mcp", "list").split()
    read_connection = next((t for t in tools if t.endswith("read_connection")), "")
    read_datasets = next((t for t in tools if t.endswith("read_datasets")), "")
    must(read_connection and read_datasets, f"step 3, the plugin's two tools are listed: {tools}")
    connection = call(read_connection)
    must(connection["mode"] == "Sample data"
         and [s["dataset"] for s in connection["sources"]] == list(DATASETS),
         f"step 3, read_connection: {connection}")
    datasets = call(read_datasets)
    records = {r["code"]: r for r in datasets["records"]}
    gbp = records["USD"]["instrument_id"]
    codes = {r["instrument_id"]: r["code"] for r in datasets["records"]
             if r["instrument_id"] and r["instrument_id"] != gbp}
    codes[gbp] = "GBP"
    must(records["SONIA"]["miss"] == "not held: reported missing" and gbp,
         f"step 3, read_datasets: {datasets['records'][:3]}")
    shown = page(INSTANCE, "admin", "/datasets?tab=records")
    must(all(f'data-code="{code}"' in shown for code in records),
         "step 3, Datasets shows what read_datasets answers")
    listed = {d["dataset"]: d for d in call("dashboard__list_datasets")["datasets"]}
    for dataset in DATASETS:
        entry = listed.get(dataset, {}).get("catalogue_entry", {})
        modes = ["pull"] if dataset in NOT_KEPT else ["push", "pull"]
        must(entry.get("modes") == modes and entry.get("day_time_zone") == "Europe/London",
             f"step 3, core lists {dataset} as declared: {listed.get(dataset)}")

    # 4. Licensed and entitled; sterling's prices wanted, read and recorded.
    for dataset in DATASETS:
        kept = "false" if dataset in NOT_KEPT else "true"
        runner("licence", dataset, f"kept={kept}", "retention_days=0", "derived_use=false",
               "display=true", "personal_use=false",
               "note=The Bank of England's data; served, not kept where its terms restrict it.")
        runner("entitle", "--instance", "reader", dataset, "note=The e2e's reader reads it.")
    runner("grant", "--instance", "reader", "--level", "read")
    page("reader", "read", f"/prices?subject={gbp}&date=2026-11-18&dataset={FX}&kind=close")
    until(90, lambda: f"want|{FX}|answered|{gbp}|" in store_lake(),
          "step 4, the want for sterling's prices of 18 November was not answered")
    usd = until(60, lambda: (lambda r: r if r.get("latest_day") == "2026-11-18" else None)(
        {r["code"]: r for r in call(read_datasets)["records"]}["USD"]),
        "step 4, the plugin did not record the dollar's rate of 18 November")
    must(usd["instrument_id"] == gbp, f"step 4, sterling's price in dollars: {usd}")

    # 5. The lake.
    got = named(store_lake(), codes)
    with open(".e2e/lake", "w", encoding="utf-8") as kept:
        kept.write(got)
    with open("e2e/expected.lake", encoding="utf-8") as held:
        expected = held.read()
    if got != expected:
        diff = subprocess.run(["diff", "-u", "e2e/expected.lake", ".e2e/lake"], capture_output=True, text=True)
        raise Failed(f"step 5, the lake is not e2e/expected.lake:\n{diff.stdout[-3000:]}")

    # 6. A new container records nothing twice.
    compose("up", "-d", "--no-deps", "--force-recreate", INSTANCE)
    runner("ready")
    until(120, lambda: "Wed 18 Nov 2026" in page(INSTANCE, "admin", "/?tab=sources"),
          "step 6, the new container did not read the answers again")
    until(90, lambda: f"miss|{INSTANCE}|{2 * MISSES}" in store_lake(),
          "step 6, the new container did not ask for each record again")
    time.sleep(5)
    again = named(store_lake(), codes)
    must(again == got.replace(f"miss|{INSTANCE}|{MISSES}\n", f"miss|{INSTANCE}|{2 * MISSES}\n"),
         "step 6, the new container recorded something twice:\n"
         + subprocess.run(["diff", "-u", "-", ".e2e/lake"], input=again, capture_output=True, text=True).stdout[-2000:])
    until(90, lambda: all(s["licensed"] for s in call(read_datasets)["served"]),
          "step 6, the new container never read its datasets' licences")

    print(f"e2e OK in {int(time.time() - started)}s on the plugin harness: the Bank's website "
          f"unreachable said on Connection, nothing recorded; on sample data the five records asked "
          f"by their code at boe and, held by none, reported missing and never minted; both tools "
          f"answering what the pages show and core listing the three datasets as declared, the "
          f"curves and the exchange rates pulled only; sterling's prices wanted by the reader, served "
          f"not kept, and answered by the plugin; `store lake` as e2e/expected.lake; and a new "
          f"container recording nothing twice")


def main():
    os.makedirs(".e2e", exist_ok=True)
    open(LOG, "w").close()
    try:
        run()
    except (Failed, subprocess.TimeoutExpired, KeyError, ValueError, IndexError, TypeError) as failed:
        with open(COMPONENTS, "a", encoding="utf-8") as kept:
            kept.write(compose("logs", "--no-color", check=False).stdout)
        # The lake as it stood, for the artifact.
        if os.path.exists(".e2e/lake"):
            with open(".e2e/lake", encoding="utf-8") as held, open(".e2e/lake.log", "w", encoding="utf-8") as kept:
                kept.write(held.read())
        compose("--profile", "runner", "down", "-v", "--remove-orphans", check=False)
        print(f"e2e FAILED: {failed}; the runner's log is in {LOG}, the components' in {COMPONENTS}",
              file=sys.stderr)
        return 1
    compose("--profile", "runner", "down", "-v", "--remove-orphans", check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
