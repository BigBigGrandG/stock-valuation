# Issues 03/04 R3 source, mapping, and live evidence

Checked 2026-09-12 (Asia/Shanghai), using the live Yahoo Finance provider.
The R2 source record remains preserved at `../03-04-r2/source-evidence.md`; this
R3 record supersedes only its unsubstantiated taxonomy alias decision.

## Primary industry source

The versioned industry values remain the January 2026 US tables by Aswath
Damodaran / NYU Stern:

- [US industry forward P/E](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pedata.html): page states data used as of January 2026 and labels the Forward PE column. The Semiconductor row has 66 firms and 37.29x forward P/E.
- [US industry EV/EBITDA](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.htm): the table distinguishes “Only positive EBITDA firms” from “All firms”. The all-firms aggregate is observed, not a forward operating-EBITDA target, so the engine rejects it and independently uses the configured EV system fallback.

Snapshot values carry `data_as_of=2026-01-01`, retrieval date, sample count,
USD/multiple units, forward basis/type, source URL, mapping key and scenario
spread metadata. Low/high are an explicit configured ±10% spread, not public
percentiles.

## Conservative taxonomy policy

The R3 decision is to keep only the direct singular/plural normalization
`Semiconductors -> Semiconductor`. The engine no longer maps Yahoo's
`Internet Content & Information -> Software (Internet)`,
`Beverages - Non-Alcoholic -> Beverage (Soft)`, application/infrastructure,
or other descriptive labels to a Damodaran row: the upstream sources do not
prove economic comparability merely by naming similarity. Broad and unknown
labels, including `Software`, return no benchmark and the P/E and EV metrics
degrade independently with an auditable reason; no ticker allow-list is used.

The raw live profile evidence is retained in `live_results_r3.json` with
Yahoo Finance profile source labels and exact industry/sector fields for
[NVDA](https://finance.yahoo.com/quote/NVDA/),
[GOOG](https://finance.yahoo.com/quote/GOOG/),
[AMD](https://finance.yahoo.com/quote/AMD/),
[META](https://finance.yahoo.com/quote/META/),
[KO](https://finance.yahoo.com/quote/KO/), and
[JPM](https://finance.yahoo.com/quote/JPM/). These profile labels are evidence
of the provider input, not evidence that the separate Damodaran taxonomy is
economically equivalent; unsupported labels intentionally fall back.

## Six-ticker live API evidence

`run_live_audit_r3.py` calls the production FastAPI `/api/v1/valuation/{ticker}`
route with a recording `YFinanceProvider`. For each ticker the artifact keeps
the request path, all seven raw provider model outputs entering normalization,
the complete JSON API response, selected P/E and EV layers/source labels,
warnings, model availability and DCF scenario metadata. The six calls were
HTTP 200 and used `DATA_PROVIDER=live`; no demo bundle was used.

| Ticker | Profile boundary | P/E layer | EV layer | DCF/applicability result |
| --- | --- | --- | --- | --- |
| NVDA | Technology / Semiconductors | industry (Semiconductor) | system (observed EV rejected) | available; three scenarios |
| AMD | Technology / Semiconductors | industry (Semiconductor) | system (observed EV rejected) | available; three scenarios |
| GOOG | Communication Services / Internet Content & Information | system (mapping rejected) | system | available; three scenarios |
| META | Communication Services / Internet Content & Information | system (mapping rejected) | system | unavailable; missing FCFF, no FCFE substitution |
| KO | Consumer Defensive / Beverages - Non-Alcoholic | system (mapping rejected) | system | available; three scenarios |
| JPM | Financial Services / Banks - Diversified | system | system | EV/FCF/DCF unavailable by bank applicability gate; P/E remains available |

The four core tickers and two additional actual different-industry boundaries
are not synthetic input cases. KO and JPM were evaluated through the same live
provider -> normalizer -> valuation service -> FastAPI route, and their raw
profile/financial inputs plus newly evaluated responses are retained.

## Oracle and replay evidence

`verify_r3_oracle.py` has separate checks for API-output inspection and
raw-input engine replay. It rebuilds the seven provider boundary models from
the saved raw JSON, runs the real normalizer/service/engines offline, and
compares ticker, independent P/E/EV layers and DCF availability/base value to
the captured API response. For available DCF scenarios it uses `Decimal` to
assert exact Years 3–5 linear fade rates, FCFF recurrence and Year 6 terminal
growth; unavailable DCF is accepted only with an explicit eligibility reason.

The default oracle writes `oracle_r3.json` and exits 0. `--corrupt-demo` writes
`live_results_r3.corrupt-control.json` and `oracle_r3_corrupt_control.json`,
changes only a copied API g3 value to `999`, and exits 1 with the expected
growth/cash-flow failures. The original `live_results_r3.json` is not modified.

