# ADR-0016: Give each tariff version one cited time-of-use calendar

- **Status:** Proposed (revised after the architect's review, E60)
- **Date:** 2026-11-21 (proposed)
- **Deciders:** Josh Heath (owner)

## Context

Phase 4 adds time-of-use (TOU) energy, export credits, and demand and capacity charges (roadmap; W29, E60). Its examples come from Eskom's Homeflex tariff. Two Eskom documents were read (PDF page numbers throughout):

- the *Tariffs and Charges Booklet 2026/2027* ("the book", SHA-256 `eef82b07…`, 57 pages, made in InDesign; E59);
- the *Schedule of Standard Prices for Eskom Tariffs*, effective 1 April 2026 ("the schedule", SHA-256 `915a93b2…`, 57 pages, made in Word; E60). Its text is a real text layer, but **every rate table is an embedded picture** (for example Table 13, Homeflex, on page 33).

What they show:

- **Seasons are text.** "High-demand season means the TOU Period from 1 June to 31 August of each year" (book page 8, schedule page 4); the low-demand season is 1 September to 31 May.
- **TOU hours are only drawn, in both documents.** The book's Appendix A (page 45) and the schedule's Figure 2 (page 56) draw peak, standard and off-peak hours as coloured clocks, with rings for weekdays, Saturday and Sunday and one clock per season. Neither yields any hour as text, so no TOU hour can pass the citation check as built in P2-7. That check records `passed` when the printed text is on the page, and `no_text_layer` only for a document the manifest marks as scanned.
- **The Homeflex energy columns are labelled only in pictures.** The book's table (page 28) has an empty header row; its rates (736.61 and so on) are text. The schedule's Table 13 (page 33, a picture) labels them Peak, Standard and Off Peak for each season, with the same rates. The book's Gen-offset Homeflex table (page 43) has the same layout with text labels.
- **Public holidays are tariff-specific.** The book (Appendix D, page 50) lists the holidays from 1 April 2026 to 30 June 2027 and how Megaflex, Miniflex, WEPS and Nightsave Urban treat each one. It says "All public holidays for the Nightsave Rural, Homeflex, Ruraflex and Ruraflex Gen tariffs will be treated as the day of the week on which it falls". The schedule says the same (page 12), but pypdf extracts that page's "week" as "we ek". **Public holidays change nothing in a Homeflex bill.**
- **Seasons are already in data, per component.** `SeasonalEnergy` carries its own seasons (TD-11).
- **Consumption can already be given per bucket.** `TimeOfUseBuckets` is accepted and refused by the engine until P4; duplicate JSON keys in it are silently merged (a P4 note).
- **Pro-rating** is by days "at times of price increase and seasonal charges" (book Appendix I, page 56). Its example divides a 31-day period into 15/30 and 16/30, so the method stays `estimated`.

Constraints: no tariff value in code (rule 1); the domain stays pure; published files are canonical and never edited (ADR-0012); a value whose text cannot be checked stays `estimated` until a human checks it (ADR-0006; E37, W8). The roadmap requires an ADR for a new component type.

## Decision

1. **One calendar per tariff version.** A version that has TOU or seasonal components carries one `TouCalendar` in its header. The calendar holds:
   - **seasons:** names and cited dates (the existing `SeasonDates`), covering every day of the year once;
   - **day types:** `weekday`, `saturday` and `sunday`, assigned from the date;
   - **holiday treatment:** a cited rule. Either every holiday is treated as the day of the week it falls on, or there is a cited list of dates, each treated as `saturday` or `sunday`, plus a cited rule for holidays not on the list. The list comes from the tariff's own document (the book's Appendix D), not from a national calendar, because the supplier's document decides how it bills;
   - **TOU periods:** for each season and day type, cited hour ranges `[start, end)` in South African Standard Time (UTC+02:00, no daylight saving) that cover the 24 hours once. Each range names a period: `peak`, `standard` or `off_peak`.

   Components refer to the calendar by season and period name. A name the calendar does not define is refused when the version is built.

2. **TD-11 closes by a check, not a rewrite.** `SeasonalEnergy` keeps its own season dates, so the published Tariff B files stay valid unchanged. A version that has both a calendar and a `SeasonalEnergy` is refused unless the component's seasons match the calendar's seasons of the same names, day for day.

3. **The calendar is a new optional header field under `schema_version` 1, omitted when absent.** **General rule for every field added under an existing schema version:** the field is optional, absent by default, and left out of the canonical output when absent. Every published file must stay byte-identical to the model's canonical output, and a test re-serialises every published file and compares the text. A field that cannot follow this rule (a required field, or a changed meaning) needs a new schema version and a converter (ADR-0012).

4. **Two consumption inputs, built in this order:**
   - **TOU buckets:** kWh used and kWh exported per TOU period for the billing period. A period that crosses a season boundary, a tariff change or a VAT change is split by the version's `BillingPolicy`, as in P1 (the book's Appendix I says by days). Duplicate keys and unknown period names are refused.
   - **Interval readings:** kWh used and exported per interval, at any one fixed interval length that divides an hour (1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30 or 60 minutes), the same throughout one profile. Each interval's start is an offset-aware timestamp; any offset other than +02:00 is refused, and naive timestamps are refused. The calendar classifies each interval into its season, day type and period, and the engine then prices the resulting buckets. A missing or overlapping interval, one that does not start on a multiple of its length, or one that crosses a period boundary is refused. Readings are calculation inputs only; they are never stored or logged (ADR-0008).

5. **A value that appears only in a picture gets a new citation-check outcome, `drawn`.** The outcome is distinct from `no_text_layer`, which means the whole document is a scan. Its rules:
   - The source manifest lists, per document, the pages that carry drawn values and says what is drawn on each. The publish step accepts `drawn` only for a citation on a listed page whose printed text is not found in the page's text layer. On any other page, a missing text is `failed`, as now.
   - A `drawn` value stays `estimated` until the owner checks it by eye against the page. It then becomes `Verified`, with method "visual comparison with the source page".
   - **Envelope change:** `checks.citation_check` gains an optional count `drawn`. An absent count means 0, so every published file stays valid and byte-identical under point 3's rule. The publish step's tool label rises from "munisense publish 2" to "munisense publish 3", which always writes `drawn`. The publication guards re-check added publications against the current label (P2-9), so a file written by label 2 is never re-checked under label 3.
   - First uses: the TOU hours (book page 45), and the schedule's Table 13 values that the book misprints or does not label (P4-11).

6. **New component types** (the roadmap requires an ADR for each). Every rate is cited, and every name is checked against the calendar:
   - `TimeOfUseEnergy`: a rate per season and period, applied to the kWh used in that bucket;
   - `ExportCredit`: a credit rate per season and period. The credited kWh in each period of each calendar month is the smaller of the kWh exported and the kWh used in that period: the book says "up to and equal to the consumption per time-of-use period" (page 28), and the schedule says "shall not be greater than the active energy (kWh) measured … for each month" (page 53);
   - `QuantityCharge`: a monthly charge per unit of a quantity the customer gives for the month (a measured maximum demand in kVA, or a notified or available capacity). Its rate unit is new (for example R/kVA per month), and it can be limited to seasons and to the periods in which the demand is chargeable. It covers the roadmap's "demand" and "capacity". Daily capacity charges that depend only on supply size, such as Homeflex's network and generation capacity charges in R/POD/day, stay `FixedCharge`s on a tariff code per supply size (E37, Q5).

## Consequences

- Good:
  - Each version has one cited calendar, used by every TOU and seasonal component, so components cannot disagree on seasons or hours.
  - Holidays are data scoped to a tariff version, as the supplier states them.
  - Bucket input works for anyone with a TOU bill. Interval input lets a smart-meter or inverter export be priced at its own resolution, which P5's tariff comparison with solar export needs.
  - The optional-field rule keeps every published file valid without converters.
- Bad:
  - TOU hours rest on a picture. Every TOU result carries an `estimated` status until the owner checks them.
  - Bucket input trusts the user's split between periods.
  - Interval classification adds code that a bucket-only design would not need.
  - Eskom lists holidays to 30 June 2027 only, so a 2027/28 version needs the next book's list.
  - `drawn` adds a fourth way for a value to get its status, so it must stay narrow: listed pages only.
- Cost now and later: R0. No new dependency.
- Reversibility: moderate. The calendar is optional, so removing it later needs a converter only for files that use it. Points 4 to 6 can each be dropped before they are built.

## Alternatives considered

| Option | Why not |
| --- | --- |
| A calendar per component (extend TD-11's current shape) | TOU energy, the export credit and a quantity charge would each repeat the hours and could disagree, which is TD-11's problem |
| A national public-holiday calendar as its own published dataset, cited to the Public Holidays Act 36 of 1994 | The supplier's document decides billing, and for Homeflex no holiday changes anything. The Act gives rules rather than dates (Good Friday and Family Day follow Easter), and gov.za's copy is a 1994 Gazette scan whose OCR errors fail the text check. It may be needed later for a supplier that bills by the national calendar without listing dates |
| Buckets only, no interval readings | Leaves the calendar's hours unused by any calculation, and users would have to split their own kWh by period |
| Interval readings at 30 minutes only | Meters and inverters export 5, 15 and 60 minutes as well; any length that divides an hour keeps period boundaries on interval edges |
| Treat drawn values as `failed` | No TOU tariff could then be published from either Eskom document |
| Reuse `no_text_layer` for drawn values | It means "the whole document is a scan", and the guards rely on that meaning. A page with a text layer and a drawn table is a different case |
| Read the TOU hours from another document that prints them as text | Checked (W28, E60): the schedule draws them too |
| A new `schema_version` for the calendar and the `drawn` count | Neither changes the meaning of existing files; under point 3's rule old files stay byte-identical, so a converter would do nothing |
