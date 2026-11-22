# Eskom: source documents

Committed source PDFs for Eskom's 2026/27 tariffs (P4, ADR-0016), listed for machines in `sources.json` (a test checks that it agrees with this file). Both were downloaded on 2026-11-21 from eskom.co.za only, from the "2026/2027 tariff increase" page, with the owner's approval: the tariff book under E59, the schedule under E60. Citations name the SHA-256. Publisher: Eskom.

**Page numbers in citations are PDF page numbers (1-based).** In the tariff book, the printed page number is one higher from PDF page 7 on (PDF page 28 is printed "Page 29"). Citations name the PDF page; a locator may add the printed page.

| File | Document | URL | SHA-256 | Size | Text layer |
| --- | --- | --- | --- | --- | --- |
| `tariffs-and-charges-booklet-2026-27.pdf` | Tariffs and Charges Booklet 2026/2027 ("the book"; made in InDesign; Last-Modified 2026-07-06) | <https://www.eskom.co.za/distribution/wp-content/uploads/2026/07/Eskom-Tariff-booklet_Final.pdf> | `eef82b077d7df4dd7b157ce757e2e56368170cec3bb69614fd81042451a1be84` | 4,125,094 bytes, 57 pages | Yes, on every page. The TOU hours (page 45) are drawn, not printed |
| `schedule-of-standard-prices-2026-27.pdf` | Schedule of Standard Prices for Eskom Tariffs, 1 April 2026 to 31 March 2027 for non-local authority supplies, and 1 July 2026 to 30 June 2027 for local authority supplies ("the schedule"; made in Word; Last-Modified 2026-03-17) | <https://www.eskom.co.za/distribution/wp-content/uploads/2026/03/20260226-Schedule-of-standard-prices-for-01-April-2026-Public-1.pdf> | `915a93b2d71a453855e76a3ffe2223826f9f63a89bb542d58f92249f52c4d675` | 7,208,097 bytes, 57 pages | Yes for its prose. Its tariff rate tables (pages 14 to 43), Table 35 (page 48), Tables 36 and 37 (excess network capacity charges, pages 49 and 50) and Table 43 (Gen-offset rates, page 54) are embedded pictures; Tables 21 to 34 (pages 44 to 48) are text. The TOU hours (page 56) are drawn |

The book's cover says the same as the schedule's title: non-local-authority charges run from 1 April 2026 to 31 March 2027, and local-authority charges from 1 July 2026 to 30 June 2027.

## What each supports

- **The book, page 1:** "Charges for non-local authorities effective from 1 April 2026 to 31 March 2027", the tariff year for non-local-authority charges. Cited in `data/catalogue/suppliers.json` for `eskom-direct`'s tariff-year start month (`estimated`: one year's dates, assumed the same each year).
- **The book, page 27:** Homeflex's description and supply sizes. **Page 28:** Homeflex charges. **Page 43:** Gen-offset Homeflex credit rates. **Page 8:** seasons. **Page 45:** TOU hours (drawn). **Page 50:** public holidays. **Page 56:** pro-rating. For P4-13.
- **The schedule, page 33:** Table 13, the Homeflex rates as a picture, with the column labels the book lacks and the figure R62.89 where the book prints R52.89 (see "Source inconsistencies" in `docs/status.md`). **Page 56:** TOU hours (drawn). For P4-13.

Values that are only drawn cannot pass the text check until ADR-0016 point 5's `drawn` outcome is built (P4-11). Until then this manifest has no `drawn` list.

## Extraction needs (P4-2)

The whole of each document was extracted through the citation check's limited child process (P2-7's `Limits`), three runs each, on the owner's machine, measuring the child's CPU with `resource.getrusage(RUSAGE_CHILDREN)` around `extract_pages` and finding the address space by retrying with lower `address_space_bytes`: the schedule took 1.5 to 1.6 s of CPU time (1.8 to 2.3 s wall), and the book took 1.1 s (1.2 to 1.8 s wall). Both fit in 128 MB of address space and fail in 96 MB (the limit is 2 GiB). The schedule is the largest committed file, so the file-size margin is now about 9x (`Limits` docstring).

## Checked and not relied on

- Public Holidays Act 36 of 1994 (gov.za): downloaded for the P4 plan and not committed (E60). No P4 value rests on it: the book's Appendix D says how Eskom treats each holiday.
