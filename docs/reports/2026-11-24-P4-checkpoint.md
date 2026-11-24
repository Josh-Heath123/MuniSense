# P4 checkpoint after P4-10: the time-of-use engine (2026-11-24)

For the architect and the owner. P4-2 to P4-10 are built, reviewed and merged. This is the stop point the P4 task list sets after the engine, before the `drawn` citation outcome (P4-11), storage (P4-12) and the Homeflex data (P4-13). **Nothing has been published in P4**: every time-of-use figure in the tests is a made-up fixture, except the Eskom book's cover dates (catalogue) and one Miniflex rate reproduced in a test.

## What is built

| Task | Pull request | What it does | Reviews |
| --- | --- | --- | --- |
| P4-1 TOU ADR | #48 | ADR-0016 accepted (E61) | architect, twice |
| P4-2 Eskom sources | #49 | The 2026/27 tariff book and schedule committed byte for byte with manifest and README; `eskom-direct` in the catalogue (non-local-authority, year from April, cited to the book's cover); committed PDFs read only through the limited child; extraction measured (1.1 to 1.6 s CPU; under 128 MB) | code APPROVE; security CHANGES REQUIRED (margins overstated, PDFs parsed in the test process), then APPROVE; tariff-verifier VERIFIED |
| P4-3 One cited walker (TD-16) | #50 | One `iter_cited` in the domain; a test finds by inspection every model that can hold a cited value and fails if one has no instance (it found `Bill`, `PeriodBill`, `Purchase`) | code and security APPROVE |
| P4-4 TOU consumption input | #51 | `used_kwh` / `exported_kwh` per `TouPeriod`; `services.consumption.parse_consumption_json` refuses duplicate JSON keys and raises only fixed-text `ConsumptionJsonError` | security CHANGES REQUIRED twice (input echoed in errors, then field paths), code CHANGES REQUIRED twice, then both APPROVE |
| P4-5 The calendar | #52 | `TouCalendar`: cited seasons, one day schedule per season and day type of cited minute ranges | code CHANGES REQUIRED (both fixture seasons shared hours, so a season-blind lookup passed), then APPROVE; security APPROVE |
| P4-6 Holidays, TD-11 | #53 | Holiday treatment (as the day of the week, or a cited list with a coverage window); `TariffVersion.tou_calendar` omitted when absent (published files byte-identical); seasonal components must agree with the calendar and each other (TD-11 closed) | code and security CHANGES REQUIRED, then APPROVE |
| P4-7 TOU energy | #54 | `TimeOfUseEnergy`; pricing from kWh per period; splitting at calendar seasons; a warning whenever kWh are shared across seasons | code CHANGES REQUIRED (the VAT property never compared VAT with the rate), security should-fixes (unbounded season scan), then both APPROVE; coverage found and fixed a bug |
| P4-8 Export credit | #55 | `ExportCredit`, capped by use per period per calendar month (`BillingPolicy.export_cap`); a negative bill refused | both CHANGES REQUIRED: over several months the cap was one cap on the whole period and could over-credit; fixed by allowing exports only on one calendar month; then both APPROVE |
| P4-9 Quantity charge | #56 | `QuantityCharge` per kVA per month on `CustomerQuantities` (strict input); the Miniflex network capacity line by hand (R54.22 x 100 kVA = R5,422.00, book PDF page 19) | both CHANGES REQUIRED (one quantity charged for every month; no input validation), then a mid-month regression, then both APPROVE |
| P4-10 Interval readings | #57 | `IntervalReadings` (any length dividing an hour, +02:00, contiguous, at most 44,640); `billing/intervals.py` classifies each interval with its part's calendar; parts priced from their own readings | both CHANGES REQUIRED (a period wholly inside one interval was billed at the wrong rate; no error codes), then both APPROVE |

Every task went through `/review` (code and security reviewers, the tariff-verifier where data changed), and every fix was re-reviewed until both approved.

## Evidence (on `main`, 2026-11-24)

- `uv run poe verify`: 1,387 tests passed, 100% line and branch coverage, 11 import contracts kept, 36 hook tests.
- `uv run poe audit`: no known vulnerabilities.
- `uv run poe check`: 27.2, 30.3, 30.4, 30.5 and 31.2 s (median 30.4 s; load average 1.2). E43's limit is 25 s; see W31.
- CI green on every merged pull request (#48 to #57).
- Mutation testing has not been re-run since P2; P4-15 runs it over `domain.billing` and the new time-of-use code (E61).

## Questions for the architect and the owner

1. **Time-of-use input on a tariff without time of use** (P4-7, P4-10). kWh per period and interval readings are refused on a flat or block tariff, not summed. Summing is exact (the total is the same), and P5's tariff comparison with solar export will want to price one customer's readings on several tariffs. Recommendation: allow summing for used kWh in P5, keep exports refused on a tariff without a credit.
2. **Exports from interval readings** (P4-10). They keep P4-8's rule: credited only on a bill of exactly one calendar month priced in one part. Readings, unlike buckets, could show each part's use, so a month split by a tariff change could be credited part by part. Recommendation: keep the rule until a source says how Eskom credits a month with a tariff change.
3. **Readings must cover the billing period exactly**, midnight to midnight SAST (P4-10). A meter export labelled by interval end (first reading 00:30) is refused, not shifted. Recommendation: keep; P5 documents that starts are interval-start labels.
4. **Moved criterion** (P4-7 to P4-10, reported at the time): "a `HolidayCoverageError` becomes a refusal". It is a `DomainError` (a refusal), but pricing cannot reach it, because P4-6 requires a holiday list to cover every day of its version. It is shown on the calendar directly. Recommendation: accept.
5. **Rules stricter than ADR-0016**, added by the reviews:
   - a holiday list must cover every day of its version, which must have an end date, and at most 731 days (P4-6);
   - a bill with exports, or with a demand or capacity charge, covers exactly one calendar month (P4-8, P4-9);
   - a negative bill is refused (P4-8);
   - a billing policy with an export cap cannot be shared with a tariff without a credit (P4-8).

   Each fails closed. Recommendation: accept, and revisit when real bills show otherwise.
6. **W31, `poe check` over 25 s.** Now a median of 30.4 s on `main`. Recommendation unchanged: raise the limit to the median plus 5 s (35 s), as E51 did; the property tests are about 1 s of it.

## What is not verified, and why

- **No Eskom tariff value is published or verified.** Homeflex drafts come in P4-13, with the owner's hand check.
- **The TOU hours are drawn, not printed**, in both Eskom documents; the `drawn` outcome that lets the owner verify them by eye is P4-11.
- **The Homeflex column labels and Homeflex 3's network capacity charge** (R52.89 in the book, R62.89 in the schedule) wait for P4-13's hand check; proposed readings are in the status file.
- **Gen-offset Homeflex**: whether paragraph 46's ancillary credit and administration charge apply to Homeflex, and whether it is a separate tariff, is a P4-13 question.
- **Methods read as policy**, each `estimated` until a real bill confirms it:
  - sharing kWh by days across a season change (always warned);
  - reading Eskom's "each month" as the calendar month for the export cap (warned while the policy is unverified);
  - rounding credits by magnitude.
- **The P5 controls the register now relies on are designed, not built**: a body size limit and CPU budget for consumption input (the largest valid interval profile is about 4.6 MB and about 1.6 s to parse), parsers that show only fixed text, and never logging bills or inputs.
- **Whether interval readings and customer quantities are personal information**, and on what basis they are processed, needs formal verification (security register).

## Values marked `estimated`

- `eskom-direct`'s tariff-year start month (4), cited to the book's cover; one year's dates assumed to repeat.
- The Miniflex rate in the P4-9 test (a test fixture, not published).
- Every time-of-use rate, hour and season in the tests is a fixture marked "not real tariff data".

## Deviations from the plan

- The P4-7 criterion on `HolidayCoverageError` moved to P4-10 (question 4).
- `parse_consumption_json` lives in `services`, not the domain, because the domain may not import `json` (P4-4).
- `needs_calendar` was found to mean two things; P4-9 split it: `prices_by_period` (time-of-use energy or an export credit) for consumption, `needs_calendar` for whether a calendar is required.

## Technical debt

- **Added:** TD-19 (no byte limit when reading drafts; due before any upload path).
- **Closed:** TD-11 (P4-6) and TD-16 (P4-3).

## Still to come in P4

P4-11 (`drawn` outcome), P4-12 (storage for the new shapes), P4-13 (Homeflex drafts, the owner's hand check, publication), P4-14 (Homeflex examples), P4-15 (gate report with mutation testing). W23 (psycopg-binary, from 2026-11-26) and W24 (the `postgres:17` digest, from 2026-12-02) are done at natural breaks once their dates pass.

**Stopped for the architect's checkpoint review.**
