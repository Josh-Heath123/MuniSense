# City of Ekurhuleni: source documents

Committed source PDFs (ADR-0006), listed for machines in `sources.json` (P2-6; a test checks that it agrees with this file). Each is identified by its SHA-256; citations name that hash, not the file name. Downloaded only from the official municipal website (E26).

## Electricity tariffs 2026/27 (the document we cite)

| Field | Value |
| --- | --- |
| File | `electricity-tariffs-2026-27-signed.pdf` |
| Title (printed) | Schedule "2": Supply of electricity tariffs for the 2026/2027 financial year, version 2026.07.30 |
| URL | <https://www.ekurhuleni.gov.za/wp-content/uploads/2026/07/Schedule-2-of-Electricity-Tariffs-2026-27-aligned-with-NERSA-rates-approved-on-23-May-2026-v.26.07.30-signed.pdf> |
| Retrieved | 2026-11-17; downloaded again 2026-11-18 with an identical hash. Server last-modified 2026-08-06 |
| SHA-256 | `db55c0d359b41469d766c6196c51b59cbfe469a139b334f9c87195a92dc07e73` |
| Size | 3,264,244 bytes, 37 pages (A4, stored rotated 270 degrees) |
| Status printed on page 1 | "Tariffs based on NERSA's approved tariffs - 23 May 2026. Noted and adopted by Council per resolution A-ENG BU (06-2026) on 30 July 2026." Start 1 July 2026, end 30 June 2027. Each page: "Approved by NERSA on 23 May 2026", signed by the Head of Business Unit: Energy, initialled |
| Text layer | **None.** Every page is a scanned image; `pdftotext` returns no text. See "Hazards" |

The same file is also published at `.../uploads/2026/08/` with the same name; it is byte-identical (same SHA-256).

## Residential tariffs in this document

Read from page images rendered with `pdftoppm` (150 dpi for pages 3 and 4, 110 dpi for 6 and 7, 60 dpi elsewhere). Not yet checked by the tariff-verifier agent or a human; values transcribed in P1-9 will be `estimated` (E29).

| Tariff | Page | Applies to (as printed, summarised) | Charges printed |
| --- | --- | --- | --- |
| A Residential (general conditions) | 3 | Qualifying residential, single- or multi-phase, up to 60 A per phase; "low consumption residential customers who are on prepayment or post-paid metering" | See A.1 and A.2 |
| A.1 Residential (Indigent) | 3 | Customers qualifying under the Indigent Support Policy | Energy: 50 kWh free per FBE policy; above 50 kWh R/kWh. No basic charge |
| A.2 Residential (non-indigent) Low income | 3, 4 (notes) | Low-income, low-usage customers not qualifying as indigent; moved to B if average use exceeds 750 kWh/month over 6 months, or if they have solar PV | Energy R/kWh, high-demand season (June to August) and low-demand season (September to May), same value in both. No basic charge |
| B Residential | 4, 5 | Full-title residential, single- or multi-phase; "medium to high consumption residential customers who are on prepayment or post-paid metering" | Basic charge R/point of supply/month (1-phase, 3-phase), "whether electricity is consumed or not", charged "once per month only per point of supply"; optional internet display R/month; energy R/kWh per season (same value in both); embedded-generation credit R/kWh. Also available for internal streetlights, guard houses, booms and gates |
| B Bulk Residential Resellers | 6, 7 (notes) | Bulk supplies to sectional-title complexes, body corporates, blocks of flats | Basic charge R/month by voltage; energy R/kWh by voltage, one "All Seasons" value each; generation credit, all seasons |
| H Residential Time of Use | 7, 8 | Full-title residential up to 150 A per phase or 100 kVA, "typically" above 1000 kWh/month; "dependent on the availability of advanced metering infrastructure and smart meters" | Basic charge R/month by connection size, "excluding prepayment metering customers"; energy R/kWh by season and peak/standard/off-peak; generation credit per season (page 8). TOU periods: page 31, but printed under Tariff J's notes and not referred to from H; applying them to H is an inference (page 37 note 3 says tariffs follow Eskom's TOU periods) |

**Prepaid and credit are not separate tariffs.** A (A.1 and A.2) and B each state that they apply to customers on prepayment or post-paid metering. A customer's tariff is set by indigent status, consumption (750 kWh/month over 6 months), solar PV and title type, not by meter type. Meter type matters elsewhere only in narrower ways: H's basic charge is printed "excluding prepayment metering customers" (page 7), which is **ambiguous** (prepaid H customers pay no basic charge, or H is not offered to prepaid customers at all); generation credits (B R.5, RR.3, H.5) need a four-quadrant bidirectional AMR meter; and a tariff change takes effect from the next billing cycle for credit and AMR meters but on receipt of the application for prepayment meters (page 32). This goes in the P1-10 report (E27).

Other pages relevant to residential customers: definitions (1, 2); miscellaneous charges, including tariff changes and prepaid-meter items (32 to 37); deposit schedule (36, 37).

## Hazards

1. **Scanned, no text layer.** The ADR-0006 deterministic check (cited printed text found on the cited page) cannot run on this document; citations will carry `TextCheck.NO_TEXT_LAYER`, and a value can reach `verified` only through a human check. Discussed in the P1-10 report.
2. **Number formats are inconsistent.** Tariff energy charges and credits print to four decimal places in R/kWh as `R 3.06,35` or `R3.37,00` (a point, two digits, a comma, two more digits; the space after "R" varies), read as R3.0635 and R3.3700. A.1's zero prints `R 0.00,00`, which only makes sense as R0.0000. Basic and miscellaneous charges print to two decimal places in rand (`R109.78`). Elsewhere the same document uses a comma as the decimal point (`R3 669,90`, `R27 466,20` on page 36; `0, 334 kilowatt` on page 35), no thousands separator (`R1750.00`, page 32), a space as thousands separator (`R1 581.80`), and an R/kWh price to two places (`R4.37 per kWh`, page 35). The four-place reading of `3.06,35` is the only plausible one (R306.35/kWh is not), but it is an inference from format and magnitude and must be confirmed (for example against a vending receipt) before any value is `verified`. Transcription must keep every printed digit and record the printed text verbatim.
3. **Units.** Energy charges are printed in **R/kWh**, not c/kWh. Basic charges are R per point of supply (POS) per month.
4. **VAT.** Page 1: "All tariffs listed below, show VAT excluded." The VAT rate itself is not in this document and needs its own cited source.
5. **Seasons.** High-demand season June to August; low-demand season September to May. For A.2 and B both seasons carry the same value in 2026/27, but they are printed as separate values and should be transcribed as such. Reseller energy charges and credits print one "All Seasons" value; H's credits differ by season.
6. **Pro-rating and tariff changes.** Page 1: "The cross-over from existing tariffs to new tariffs will be billed pro rata." Page 32 (miscellaneous charge 1, note 1): a customer stays on a new tariff for at least 12 months; a change takes effect from the next billing cycle for credit and AMR meters, and on receipt of the application for prepayment meters. Both relevant to period splitting (P1-13).
7. **Adopted after the start date.** Effective 1 July 2026 but noted and adopted by Council on 30 July 2026. Page 1 also mentions an interim billing measure for tariff E customers (not residential).
8. **Policies outside this document.** Free Basic Electricity (A.1's 50 kWh) is governed by the FBE policy; indigent status by the Indigent Support Policy; prepaid vending by a separate vending policy (budget Annexure E14, found on the website; this schedule does not name it). How B's monthly basic charge is recovered from a prepaid customer is not stated on the residential or miscellaneous pages (pages 9 to 30, non-residential, were not read in full).
9. **Prepaid conversion allocation.** A customer converting to prepayment receives a once-off 40 kWh allocation, recovered as an arrear "with the first monetary transaction" (pages 3 and 5). This is not a tariff value, but it affects the first prepaid purchase.
10. **Earlier versions with different figures are on the same website.** See below. Always cite by SHA-256. Page 37 ("Tariff approval") supports citing this copy: "If the tariffs approved by Council differ from the tariffs approved by NERSA, the NERSA approved tariffs shall be applied, until the matter is resolved."
11. **Values may change during the year.** Page 37 note 3: changes from Eskom's Retail Tariff Structural Adjustments "will be effected immediately".
12. **Charges outside this schedule.** Page 1: any penalty or incentive scheme, and any electricity levy imposed by higher authorities, are "in addition to this schedule of tariffs".
13. **Public holidays (time of use).** Pages 2 and 31: a public holiday on a weekday is treated as a Saturday, but an unexpectedly announced holiday is treated as the weekday it falls on. Page 31 also appears to contain printing errors in the Sunday off-peak hours ("19:00 to 17:00", "20:00 to 18:00").

## Other copies found on the official website (recorded, not committed)

Searched on 2026-11-18 through the site's media library for a copy of the same schedule with a text layer.

| Document | URL path (under `www.ekurhuleni.gov.za/wp-content/uploads/`) | SHA-256 | Text layer | Same figures as the signed copy? |
| --- | --- | --- | --- | --- |
| Schedule 2, v.26.04.15 "after public comments", signed | `2026/07/Schedule-2-of-Electricity-Tariffs-2026-27-v.26.04.15-after-public-comments-signed.pdf` | `33410c6c4578e66be19c7588c1cfbb99708494eefc71ec05e8fcaf25e3e7ecee` | None (scanned) | Not compared (scanned; earlier version, before NERSA approval) |
| Annexure F, 2026/27 tariffs (final budget; Schedule 2 starts at PDF page 8; A on page 11, B on 12, resellers on 13, H on 14) | `2026/06/Annexure-F-2026-27-Tariffs.pdf` | `4c245248dd59b281dc7326c751ac5fa1b744ab2da92636d404a7311acc200612` | Yes | **No.** It is the version put to Council before the NERSA approval ("Increase for Council approval based on NERSA's approval on Eskom's ERTSA increase with 9.01%"). A.1 (R2.98,79) and A.2 (R3.06,35) match. B differs: basic charge R119.67 / R222.26 against R109.78 / R203.89 signed; energy R3.67,60 against R3.37,00. Bulk resellers RR1 basic charge (R1 352.50 against R715.64 signed) and every Tariff H basic and energy charge also differ; reseller energy rates, RR2 and the generation credits match |
| Annexure F, draft tariffs (draft budget) | `2026/04/Annexure-F-Tariffs.pdf` | `517b3020a709abdb93d1d67e6f6b86c98cbb1e4e15562bd57acc0ff42b99ae74` | Yes | Not compared (draft) |
| Alphabetical index of tariffs 2026/27 | `2026/07/A-Alpha-Index-of-Tariffs-2026-2027.pdf` | `0cc6734e2dc147d0fbae1f6534538ce754dcab8a934f82e9490cd525591f8162` | Yes | An index only; no electricity figures |

**Conclusion: no copy with a text layer carries the signed 2026/27 figures.** Annexure F has a text layer, but for Tariff B (and resellers and H) it shows the pre-NERSA figures. For A.1 and A.2 its figures equal the signed ones, which helps a human check those values, but the signed copy remains the document we cite.
