# Issue 03/04 R2 source and policy evidence

Retrieved/checked 2026-09-12 (Asia/Shanghai). The implementation uses a
versioned January 2026 public industry snapshot; live requests do not relabel
current trailing fields as historical forward observations.

## Industry sources

| Metric | Primary source | Source date | Used fields | R2 compatibility |
| --- | --- | --- | --- | --- |
| Forward P/E | [NYU Stern / Aswath Damodaran US PE by sector](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pedata.html) | January 2026 | Forward PE, number of firms, industry row | Accepted only with `currency=USD`, `unit=multiple`, `basis=forward_consensus_eps`, `forecast_type=forward`, and HTTPS provenance. |
| EV/EBITDA | [NYU Stern / Aswath Damodaran US EV/EBITDA](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.htm) | January 2026 | All-firms EV/EBITDA row and number of firms | Explicitly **rejected** as a forward operating-EBITDA target: the page labels separate “Only positive EBITDA firms” and “All firms” columns, while the engine requires a forward operating-EBITDA basis. |

The primary PE page states “Data used is as of January 2026”, labels the
Forward PE column, and contains Semiconductor (66 firms, 37.29x), Software
(Internet) (29 firms, 64.81x), and Software (System & Application) (309 firms,
34.13x). The primary EV page contains the corresponding all-firms values
Semiconductor 42.70x and Software (Internet) 100.45x. These values are
copied into `backend/app/services/multiples.py` with separate PE/EV source
URLs and metadata; low/high are a configured ±10% scenario spread, not
public percentiles.

## Exact industry mapping evidence

The production resolver performs exact normalized label/alias lookup only;
there is no substring search. The boundary/replay artifact records both
inputs and results in `boundary_replay.json`:

| Upstream profile input | Resolver result | Evidence / treatment |
| --- | --- | --- |
| `Technology / Software` | no row (`None`) | Broad label is ambiguous and degrades; it cannot select Internet or System/Application by substring. |
| `Technology / Internet Content & Information` | `Software (Internet)` | Exact controlled alias to the named Damodaran row. [Yahoo Finance GOOG](https://finance.yahoo.com/quote/GOOG/) and [Yahoo Finance META](https://finance.yahoo.com/quote/META/) expose this exact profile industry label; the Damodaran PE page exposes the named Software (Internet) row. |
| `Technology / Semiconductors` | `Semiconductor` | Exact controlled alias; Damodaran exposes the named Semiconductor row. |

The economic equivalence between Yahoo's taxonomy and the Damodaran row is a
controlled policy mapping, not a claim that the sources share a common
taxonomy. If a future provider emits an unlisted or ambiguous label, the
resolver returns no benchmark and the metric independently falls back with a
warning.

## Company-history policy

No live Yahoo historical-forward series is fabricated. A company observation
is accepted only when its own archived record carries all of the following:

* observation date and quote evidence from an HTTPS source;
* forecast source and HTTPS forecast URL, with `is_forward=true`;
* forecast vintage on or before the quote date;
* target fiscal period end after the quote date (FY, not TTM/historical);
* matching USD currencies and explicit per-share (P/E) or total-value
  (EV/EBITDA) units;
* compatible diluted-common-share P/E or enterprise-value/forward-operating-
  EBITDA basis, with a contemporaneous ratio check;
* three to five years of post-filter coverage, three to five unique dates,
  latest observation age <=730 days, and deterministic duplicate/dense
  sampling.

The validator deduplicates repeated dates, selects at most five evenly spaced
rows including endpoints, applies a 3×MAD filter, then rechecks count, age and
coverage. Zero MAD retains all selected rows because no robust outlier
threshold is inferable; this behavior and the post-filter endpoint-outlier
degradation are tested in the R2 regression module. Synthetic `example.test`
URLs in tests are validator fixtures only and are never used as production
valuation data.

## R2 live/replay evidence

`live_results.json` stores raw production provider/service responses for NVDA,
GOOG, AMD and META. At the 2026-09-12 run, all four completed successfully;
each selected PE from the exact industry snapshot and independently selected
EV/EBITDA system fallback because the public EV row is observed all-firms.
META's DCF was unavailable due missing complete forward FCFF, so fade
validation is explicitly not applicable for that ticker; NVDA/GOOG/AMD pass
all replayed Years 3–5 checks. The replay result and the two boundary tests
are in `boundary_replay.json`.

## Issue 04 fade/export evidence

For every available DCF scenario, the contract is
`g_t = g_start + ((t - 2) / 3) × (g_terminal - g_start), t=3..5`, with
`g_5 = g_terminal`. The backend emits the same five annual FCFF projections
and growth rates into each sensitivity trajectory; the browser workflow and
Markdown export assert the explicit Years 3–5 line, five-year rows, and
`g_5 == terminal_growth`. The browser uses a test-only fixture subclass that
supplies explicit FY1/FY2 FCFF and bridge inputs; the production missing-FCFF
eligibility gate is unchanged.
