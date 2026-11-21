# ADR-0016: Give each tariff version one cited time-of-use calendar

- **Status:** Proposed
- **Date:** 2026-11-21 (proposed)
- **Deciders:** Josh Heath (owner)

## Context

Phase 4 adds time-of-use (TOU) energy, export credits and possibly demand charges (roadmap). Its examples come from Eskom's Homeflex tariff in the *Tariffs and Charges Booklet 2026/2027* (SHA-256 `eef82b07…`, 57 PDF pages; downloaded on 2026-11-21 under E59). What that document shows:

- **Seasons are text.** "High-demand season means the TOU Period from 1 June to 31 August of each year"; "Low-demand season … 1 September to 31 May" (PDF page 8).
- **TOU hours are a picture.** Appendix A (PDF page 45) draws peak, standard and off-peak hours as two coloured clocks (weekdays, Saturday and Sunday rings, one clock per season). pypdf extracts the headings but no hour from that page, so a TOU hour can never pass the deterministic citation check as built in P2-7 (`passed` needs the printed text on the page; `no_text_layer` applies only to a scanned document).
- **Rates are text, but the Homeflex table does not label its columns.** PDF page 28 prints six active-energy rates per season with an empty header row; the Gen-offset Homeflex table on PDF page 43 prints the same layout with "Peak", "Standard" and "Off Peak" labels. Reading page 28's columns as peak, standard, off-peak is an inference.
- **Public holidays are tariff-specific.** Appendix D (PDF page 50) lists the holidays from 1 April 2026 to 30 June 2027 and how each is treated (as a Saturday or a Sunday) for Megaflex, Miniflex, WEPS and Nightsave Urban, and says "All public holidays for the Nightsave Rural, Homeflex, Ruraflex and Ruraflex Gen tariffs will be treated as the day of the week on which it falls" and "Any unexpectedly announced public holiday not listed below will be treated as the day of the week on which it falls". **So public holidays change nothing in a Homeflex bill.** The list agrees with the gov.za public-holidays page read on 2026-11-21.
- **Seasons are already in data, per component.** `SeasonalEnergy` carries its own seasons (TD-11); a second seasonal component in the same version could disagree with it.
- **Consumption can already be given per bucket.** `TimeOfUseBuckets` (kWh per bucket name) is accepted as input and refused by the engine until P4. Duplicate JSON keys in it are silently merged (a P4 note).
- **Pro-rating.** Appendix I (PDF page 56) says bills are pro-rated by days "at times of price increase and seasonal charges". Its worked example divides a 31-day period into 15/30 and 16/30, which does not add up; the method stays `estimated`.

Constraints: no tariff value in code (rule 1); the domain stays pure; published files are canonical and never edited (ADR-0012); a value that cannot pass the text check is `estimated` until a human checks it (ADR-0006, E37 W8).

## Decision

1. **One calendar per tariff version.** A version that has time-of-use or seasonal components carries one `TouCalendar` in its header. The calendar holds:
   - **seasons:** names and cited dates (the existing `SeasonDates`), covering every day of the year once;
   - **day types:** `weekday`, `saturday`, `sunday`, assigned from the date;
   - **holiday treatment:** a cited rule, either "as the day of the week it falls on" or a cited list of dates, each treated as `saturday` or `sunday`, with a cited rule for unlisted holidays. The list comes from the tariff's own document (Eskom's Appendix D), not from a national calendar, because the supplier's document decides how it bills;
   - **TOU periods:** for each season and day type, cited hour ranges `[start, end)` in South African Standard Time (UTC+02:00, no daylight saving) that cover the 24 hours once, each naming a period (`peak`, `standard`, `off_peak`).

   Components refer to the calendar by season and period name; a name the calendar does not define is refused when the version is built.

2. **TD-11 closes by a check, not a rewrite.** `SeasonalEnergy` keeps its own season dates, so the published Tariff B files stay valid unchanged. A version that has both a calendar and a `SeasonalEnergy` is refused unless the component's seasons match the calendar's seasons of the same names, day for day.

3. **The calendar is a new optional header field under `schema_version` 1.** Published files without it load unchanged. (For the architect: ADR-0012's converter registry suggests a new schema version for a changed shape; an optional field that old files simply lack seemed not to need one. If it does, P4 adds version 2 with a converter.)

4. **Two consumption inputs, in this order:**
   - **TOU buckets** (built first): kWh used, and kWh exported, per TOU period for the billing period. A period that crosses a season boundary, tariff change or VAT change is split by the version's `BillingPolicy`, as in P1 (Eskom's Appendix I says by days). Duplicate keys and unknown period names are refused.
   - **Interval readings** (built second): kWh per half hour, each with its start in SAST. The calendar classifies each interval into its season, day type and period, and the engine then prices the resulting buckets. A missing or overlapping interval, or one that crosses a period boundary, is refused. Readings are calculation inputs only; they are never stored or logged (ADR-0008).

5. **A value printed only as a picture** (the TOU hours) gets a new text-check outcome, `not_in_text_layer`. The source manifest names the page and says what is drawn there, and the publish step accepts the outcome only on a page the manifest lists. As with a scanned page, the value stays `estimated` until the owner checks it by eye against the page and it becomes `Verified` (method "visual comparison with the source page"). The column order on page 28 is recorded the same way: `estimated`, with the reason naming page 43's labelled table, until a source prints the labels or the owner confirms it.

## Consequences

- Good: one cited calendar per version, used by every TOU and seasonal component, so components cannot disagree on seasons or hours. Holidays are data scoped to a tariff version, as the supplier states them. Bucket input works for anyone with a TOU bill; interval input lets a smart-meter or solar-inverter export be priced, which P5's tariff comparison with solar export needs.
- Bad: TOU hours rest on a picture. Until the owner checks them, every TOU result carries an `estimated` status. The bucket input trusts the user's split between periods. Interval classification adds code that a bucket-only design would not need. Eskom lists holidays to 30 June 2027 only, so a 2027/28 version needs the next tariff book's list.
- Cost now and later: R0. No new dependency.
- Reversibility: moderate. The calendar is an optional field, so removing it later means a converter for files that use it. Points 4 and 5 can each be dropped before they are built.

## Alternatives considered

| Option | Why not |
| --- | --- |
| A calendar per component (extend TD-11's current shape) | Two TOU components (energy and export credit) would each repeat the hours and could disagree, which is TD-11's problem |
| A national public-holiday calendar as its own published dataset, shared by all suppliers (cited to the Public Holidays Act 36 of 1994) | The supplier's document decides billing: Eskom says how each holiday is treated, and for Homeflex no holiday changes anything. The Act gives rules rather than dates (Good Friday and Family Day follow Easter), and the gov.za copy is a 1994 Gazette scan with an OCR text layer whose errors fail the text check ("Human Rights Da)"). It may be needed later for a supplier that bills by the national calendar without listing dates |
| Buckets only, no interval readings | Leaves the calendar's hours unused by any calculation, and P5's comparison with solar export would need users to split their own kWh by period |
| Treat TOU hours that are only in a picture as `failed` | Fails closed, so no TOU tariff could be published from this book |
| Read the hours from another Eskom document that prints them as text | Possibly better. The Schedule of Standard Prices on the same Eskom page may print them, but downloading it needs the owner's approval (W28). If it does, point 5 may not be needed for Eskom |
