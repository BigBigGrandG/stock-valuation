Issue 03 source evidence
=======================

The versioned public industry snapshot used by the live provider is based on
the following first-party public pages, both consulted on 2026-09-12:

* NYU Stern / Aswath Damodaran US Industry PE table (includes Forward PE and
  last-updated metadata):
  https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pedata.html
* NYU Stern / Aswath Damodaran US Industry EV/EBITDA table (observed all-firms
  industry aggregates):
  https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.htm

Rows copied into the explicitly dated January 2026 snapshot include:

| Public row | Sample | Forward PE | EV/EBITDA | Accounting/source note |
| --- | ---: | ---: | ---: | --- |
| Semiconductor | 66 | 37.29x | 42.70x | public industry aggregate |
| Software (System & Application) | 309 | 34.13x | 31.75x | public industry aggregate |
| Software (Internet) | 29 | 64.81x | 100.45x | observed all-firms EV aggregate |
| Semiconductor Equip | 31 | 41.58x | 26.18x | public industry aggregate |

The implementation keeps P/E and EV/EBITDA source URLs and fields separate.
The scenario low/high values use an explicit +/-10% configured spread and are
never represented as public percentiles. Unknown/stale/non-USD/low-sample
rows degrade independently to the system parameter and emit a specificity
warning; no ticker allow-list is used.

Company history is accepted only when each archived FY forward observation has
an HTTPS source URL, contemporaneous as_of and price/forward-EPS (P/E) or
enterprise-value/forward-EBITDA (EV/EBITDA) evidence, positive finite values,
at least three valid samples, one-year coverage, and bounded age/lookback.
Current Yahoo trailing fields are never relabeled as historical forward data.

Issue 04 arithmetic evidence
============================

For a controlled snapshot FCFF1=100, FCFF2=120, g_start=0.20 and terminal
growth=0.03, the backend emits:

  g3 = 0.20 + (1/3) * (0.03 - 0.20) = 0.1433333333333333333333333333
  g4 = 0.20 + (2/3) * (0.03 - 0.20) = 0.0866666666666666666666666667
  g5 = 0.03 exactly
  FCFF3=137.20, FCFF4=149.09, FCFF5=153.56, FCFF6=158.1668

PV, TV and equity values are computed from these backend projections. A
sensitivity cell changing terminal growth rebuilds only Years 3-5 from the
same g_start; Years 1-2 remain explicit and unchanged. The frontend and
Markdown exporter only render backend-provided rates/values.
