# ADR-0016: Give each tariff version one cited time-of-use calendar

- **Status:** Proposed (revised after the architect's review, E60, and the `/review` findings)
- **Date:** 2026-11-21 (proposed)
- **Deciders:** Josh Heath (owner)
- **Relation to Accepted ADRs, if accepted:**
  - It supersedes ADR-0006's first condition for `verified` (the deterministic text check), only for citations of drawn items under point 5.
  - It amends ADR-0013's version `checks` shape (point 5).
  - It replaces ADR-0004's two planned names `DemandCharge` and `CapacityCharge` with one `QuantityCharge` (point 6).
  - Point 3 states how it reads ADR-0012's constraint on byte-for-byte reproduction.

## Context

Phase 4 adds time-of-use (TOU) energy, export credits, and demand and capacity charges (roadmap; W29, E60). Its examples come from Eskom's Homeflex tariff. Two Eskom documents were read; page numbers throughout are 1-based PDF page numbers (in the book, the printed page number is one higher from PDF page 7 on):

- the *Tariffs and Charges Booklet 2026/2027* ("the book", SHA-256 `eef82b07…`, 57 pages, made in InDesign; E59);
- the *Schedule of Standard Prices for Eskom Tariffs*, effective 1 April 2026 ("the schedule", SHA-256 `915a93b2…`, 57 pages, made in Word; E60). Its prose is a text layer, but its **tariff rate tables (pages 14 to 43) are embedded pictures**, Table 13 (Homeflex, page 33) among them. The use-of-system tables on pages 44 to 48 are text.

What they show:

- **Seasons are text.** "High-demand season means the TOU Period from 1 June to 31 August of each year" (book page 8; schedule page 4). The low-demand season is 1 September to 31 May (book page 8; schedule page 5).
- **The TOU hours are drawn, in both documents.** The book's Appendix A (page 45) and the schedule's Figure 2 (page 56) draw the peak, standard and off-peak hours as coloured clocks, with rings for weekdays, Saturday and Sunday and one clock per season. Neither yields any hour as text. So no TOU hour can pass the citation check built in P2-7: it records `passed` when the printed text is on the page, and `no_text_layer` only for a document the manifest marks as scanned.
- **The Homeflex energy columns are labelled only in pictures.**
  - The book's table (page 28) has an empty header row; its rates (736.61 and so on) are text.
  - The schedule's Table 13 (page 33, a picture) labels the same rates Peak, Standard and Off Peak for each season.
  - The book's Gen-offset Homeflex table (page 43) has the same layout with text labels.
- **Public holidays are tariff-specific.**
  - The book (Appendix D, page 50) lists the holidays from 1 April 2026 to 30 June 2027 and how Megaflex, Megaflex Gen, Municflex, Miniflex, WEPS and Nightsave Urban treat each one.
  - It says: "All public holidays for the Nightsave Rural, Homeflex, Ruraflex and Ruraflex Gen tariffs will be treated as the day of the week on which it falls".
  - The schedule says the same (page 12). pypdf extracts some of its words split ("we ek"), and some of the book's too ("New Y ear's Day").
  - **Public holidays change nothing in a Homeflex bill.**
- **Export credit (Gen-offset).** The book: "for energy exported up to and equal to the consumption per time-of-use period" (page 28). The schedule (page 53, paragraph 46): "the total exported energy per TOU credited shall not be greater than the active energy (kWh) measured by Eskom in peak, standard and off-peak periods for each month". It also credits the ancillary service charge on the energy exported and adds an administration charge per day. Whether "Gen-offset Homeflex" (book page 43) is part of Homeflex or a separate reconciliation tariff on the same account is not yet settled (P4-13).
- **Seasons are already in data, per component.** `SeasonalEnergy` carries its own seasons (TD-11).
- **Consumption can already be given per bucket.** `TimeOfUseBuckets` is accepted and refused by the engine until P4; duplicate JSON keys in it are silently merged (a P4 note).
- **Pro-rating** is by days "at times of price increase and seasonal charges" (book Appendix I, page 56). Its example divides a 31-day period into 15/30 and 16/30, so the method stays `estimated`.

Constraints:

- No tariff value is in code (rule 1).
- The domain stays pure.
- Published files are canonical and never edited (ADR-0012).
- `verified` needs a deterministic text check where the PDF has a text layer, plus a recorded human verifier (ADR-0006).
- The roadmap requires an ADR for a new component type.

## Decision

1. **One calendar per tariff version that needs one.**
   - **When it is required:** a version with a component that depends on time of use (`TimeOfUseEnergy`, `ExportCredit` with per-period rates, or a `QuantityCharge` limited to seasons or periods) carries one `TouCalendar` in its header, and is refused without one. A version with only a `SeasonalEnergy`, such as Tariff B, may omit the calendar.
   - **What the calendar holds:**
     - **seasons:** names and cited dates (the existing `SeasonDates`), covering every day of the year once;
     - **day types:** `weekday`, `saturday` and `sunday`, assigned from the date;
     - **holiday treatment:** a cited rule. It is either "every holiday as the day of the week it falls on" or a cited list. A list has its own cited **coverage window** (Eskom's: 1 April 2026 to 30 June 2027), separate from the version's validity. Each listed date is treated as `saturday` or `sunday`, with a cited rule for unlisted holidays. Under a list, a day outside the coverage window is **refused**: nothing can tell whether it is a holiday, and the engine does not guess. The list comes from the tariff's own document (book Appendix D), not from a national calendar, because the supplier's document decides how it bills;
     - **TOU periods:** for each season and day type, cited time ranges `[start, end)` at minute resolution in South African Standard Time (UTC+02:00, no daylight saving) that cover the day once. Each range names a period: `peak`, `standard` or `off_peak`.
   - **How components use it:** components refer to the calendar by season and period name. A name the calendar does not define is refused when the version is built.

2. **TD-11 closes by a check, not a rewrite.** `SeasonalEnergy` keeps its own season dates, so the published Tariff B files stay valid unchanged. A version with both a calendar and a `SeasonalEnergy` is refused unless every season of the component has the same name in the calendar and the same days.

3. **The calendar is a new optional header field under `schema_version` 1, omitted when absent.** General rule for a field added under an existing schema version:
   - The field is optional and absent by default.
   - It is left out of the canonical output when absent. This is done per field, so the fields written as `null` today (for example `supersedes`, `effective_to`) keep their form.
   - Every published file **of the current schema version** must render byte-identically from today's model. `test_every_publication_is_what_its_model_writes` (`tests/unit/data/test_committed_data.py`) already checks this.
   - **How this reads ADR-0012:** ADR-0012 says that no check on a published file may depend on today's model reproducing it byte for byte. That test is a check on the **code**, not on the file. The guards and the loader still decide a file's validity from its text alone. If the test fails, the code is wrong, or the change needs a new `schema_version` and a converter (ADR-0012). It never means editing a file. Files of an older schema version are outside the test; they load through their converter.
   - A field that cannot follow this rule (a required field, or a changed meaning) needs a new schema version.

4. **Two consumption inputs, built in this order:**
   - **TOU buckets:** kWh used and kWh exported per TOU period for the billing period. A period that crosses a season boundary, a tariff change or a VAT change is split by the version's `BillingPolicy`, as in P1 (the book's Appendix I says by days). Duplicate keys are refused, and so are period names the version's calendar does not define.
   - **Interval readings:**
     - **Shape:** kWh used and exported per interval, at any one fixed interval length that divides an hour (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30 or 60 minutes), the same throughout one profile. There is a stated maximum number of intervals per profile.
     - **Times:** each interval's start is an offset-aware timestamp. Any offset other than +02:00 is refused, and so are naive timestamps.
     - **Classification:** the calendar puts each interval into its part of the period (the parts as P1-13 splits it: month, tariff version, season, VAT rate), its day type and its TOU period. The result is buckets per part, which the engine prices **without splitting them again by days**.
     - **Refused:** a missing or overlapping interval, one that does not start on a multiple of its length, one that crosses a period boundary, and one outside the billing period.
     - **Privacy:** readings show when people are at home. They are calculation inputs only, and are never stored or logged (ADR-0008). A refusal carries a fixed code and at most the interval's index, never a timestamp or a kWh figure.

5. **A drawn value gets a new citation-check outcome, `drawn`, by explicit opt-in.** It is distinct from `no_text_layer`, which means the whole document is a scan.
   - **The manifest lists each drawn item.** A source document's manifest entry gains an optional `drawn` list (following point 3's rule). Each item names a page, what is drawn there and the printed texts allowed as drawn on that page. It is allowed only for a document with `text_layer: true`, and its pages must be in range.
   - **The citation says it is drawn.** A citation gains an optional `drawn: true`.
   - **The outcome is `drawn` only when all three hold:** the citation says drawn; its page and printed text are a listed drawn item; and the text is not in the page's text layer (an empty text layer counts as "not in it"). A citation that says drawn but whose text **is** in the text layer is `failed`, so the flag cannot be used by habit. A citation that does not say drawn behaves as now: a missing text is `failed`.
   - **Status.** A `drawn` value stays `estimated` until the owner checks it by eye against the page. It then becomes `Verified`, with `text_check: drawn` (a new `TextCheck` member) and method "visual comparison with the source page".
   - **The publish step pairs them exactly.** `Verified(text_check=drawn)` is accepted only on a `drawn` outcome, and a `drawn` outcome accepts only `Verified(text_check=drawn)` or a non-verified status. **This supersedes ADR-0006's first condition for `verified`, for listed drawn items only.** Everything else in ADR-0006 stands, including the recorded verifier identity, method and date.
   - **Envelope change (amends ADR-0013):**
     - `checks.citation_check` gains a count `drawn`.
     - Files written under tool label "munisense publish 2" lack it (absent means 0) and stay byte-identical.
     - The publish step's label rises to "munisense publish 3", which always writes `drawn`, even when it is 0.
     - The guards refuse a label-3 file without `drawn`, a label-2 file with it, and an **added** label-2 file (as today, P2-9).
     - The guards compare all four counts against a re-run.
   - **The drawn list is a trusted input, so it changes apart from publications.** A pull request that adds publications may not add or change a manifest's `drawn` list, and the guards refuse one that does. The owner's checklist names every drawn item a publication relies on.
   - **First uses:** the TOU hours (book page 45), and the schedule's Table 13 values that the book misprints (P4-13).

6. **New component types** (the roadmap requires an ADR). Every rate is cited, and every name is checked against the calendar:
   - `TimeOfUseEnergy`: a rate per season and period, applied to the kWh used in that bucket.
   - `ExportCredit`: a credit rate per season and period, or one rate for all periods (for credits such as the ancillary service charge on energy exported). The credited kWh in each period is at most the kWh used in that period over the same month. The sources say "each month"; reading that as the calendar month is a billing-policy reading, recorded `estimated` until a source confirms it. A credit is a negative line.
   - `QuantityCharge`: a monthly charge per unit of a quantity the customer gives for the month (a measured maximum demand in kVA, or a notified or available capacity). It has a new rate unit (for example R/kVA per month), and can be limited to seasons and to the periods in which the demand is chargeable. It covers the roadmap's "demand" and "capacity", and replaces ADR-0004's two planned names. Daily capacity charges that depend only on supply size, such as Homeflex's network and generation capacity charges in R/POD/day, stay `FixedCharge`s on a tariff code per supply size (E37, Q5).

## Consequences

- Good:
  - Each version that needs a calendar has one cited calendar, used by every TOU component, so components cannot disagree on seasons or hours.
  - Holidays are data scoped to a tariff version, as the supplier states them, and a day outside the list's coverage is refused rather than guessed.
  - Bucket input works for anyone with a TOU bill. Interval input prices a smart-meter or inverter export at its own resolution, which P5's tariff comparison with solar export needs.
  - The optional-field rule keeps every published file valid without converters.
- Bad:
  - TOU hours rest on a picture, so every TOU result carries an `estimated` status until the owner checks them.
  - Bucket input trusts the user's split between periods.
  - Interval classification adds code that a bucket-only design would not need.
  - Eskom lists holidays to 30 June 2027 only, so a 2027/28 version needs the next book's list.
  - `drawn` adds a way for a value to reach `Verified` without a text check. It is held narrow by the per-citation opt-in, the listed printed texts, and the rule that a drawn list never changes in a publication pull request.
- Cost now and later: R0. No new dependency.
- Reversibility: moderate. The calendar is optional, so removing it later needs a converter only for files that use it. Points 4 to 6 can each be dropped before they are built.

## Alternatives considered

| Option | Why not |
| --- | --- |
| A calendar per component (extend TD-11's current shape) | TOU energy, the export credit and a quantity charge would each repeat the hours and could disagree, which is TD-11's problem |
| A national public-holiday calendar as its own published dataset, cited to the Public Holidays Act 36 of 1994 | The supplier's document decides billing, and for Homeflex no holiday changes anything. The Act gives rules rather than dates (Good Friday and Family Day follow Easter), and gov.za's copy is a 1994 Gazette scan whose OCR errors fail the text check. It may be needed later for a supplier that bills by the national calendar without listing dates |
| Under a holiday list, treat days past the coverage window as ordinary days | That is a guess: a holiday after 30 June 2027 would be billed as a weekday with no warning |
| Buckets only, no interval readings | Leaves the calendar's hours unused by any calculation, and users would have to split their own kWh by period |
| Interval readings at 30 minutes only | Meters and inverters also export at 5, 15 and 60 minutes; any length that divides an hour keeps period boundaries on interval edges |
| `drawn` for every missing text on a listed page | A mistyped or wrong value cited to that page would publish as `estimated` instead of failing (the security review's finding) |
| Treat drawn values as `failed` | No TOU tariff could then be published from either Eskom document |
| Reuse `no_text_layer` for drawn values | It means "the whole document is a scan", and the guards rely on that meaning |
| Read the TOU hours from another document that prints them as text | Checked (W28, E60): the schedule draws them too |
| A new `schema_version` for the calendar and the new counts | Neither changes the meaning of existing files; under point 3's rule, old files stay byte-identical, so a converter would do nothing |
