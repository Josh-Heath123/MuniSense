# South African Revenue Service: source documents

Committed source PDFs for the VAT rate (ADR-0006), listed for machines in `sources.json` (P2-6; a test checks that it agrees with this file), downloaded from the official SARS website on 2026-11-18 with the owner's approval (E33). Citations name the SHA-256. Page numbers in citations are PDF page numbers.

| File | Document | URL | SHA-256 | Size | Text layer |
| --- | --- | --- | --- | --- | --- |
| `vat-404-guide-for-vendors-2025-01.pdf` | VAT 404 Guide for Vendors (SARS publication, created 16 January 2025) | <https://www.sars.gov.za/wp-content/uploads/Ops/Guides/Legal-Pub-Guide-VAT404-VAT-404-Guide-for-Vendors.pdf> | `9204c3f8d0cea0200b84559f19bfa638d2f6eb6e2083ac633da4938eec52c31a` | 1,749,964 bytes, 176 pages | Yes |
| `rates-and-monetary-amounts-act-3-of-2026.pdf` | Rates and Monetary Amounts and Amendment of Revenue Laws Act 3 of 2026, Government Gazette 54446, 1 April 2026 | <https://www.sars.gov.za/wp-content/uploads/Legal/AmendActs/Legal-LPrim-AA-2026-01-Rates-and-Monetary-Amounts-and-Amendment-of-Revenue-Laws-Act-3-of-2026-GG-54446-1-April-2026.pdf> | `5f6e4225703d6ba2f0d19bd0911fe580f787bcab4d1f8d6f421525051366ad1e` | 575,232 bytes, 32 pages | Yes |

## What each supports

- **VAT 404, page 15** (Chapter 1, 1.2 "How does VAT work?"): "at the standard rate of 15%", and footnote 5: "The standard rate of VAT changed from 14% to 15% with effect from 1 April 2018." Cited for the percentage and the start date in `data/vat/south-africa/2018-04-01.r1.json` (published in P2-13).
- **Act 3 of 2026, page 10, section 13**: the VAT rate increase announced in the 2025 national budget "does not come into effect", deemed from 1 May 2025. This is why the 15% entry has no end date. The domain model cites one document per value, so this Act is named, with its full SHA-256, in the VAT publication's reason (the percentage is `verified`, and a verified status has no reason field), not as a citation; a test checks that hash against the committed file.

## Why not the VAT Act itself

SARS's list of Acts links the Value-Added Tax Act 89 of 1991 only to an interactive LexisNexis portal, not to a downloadable document. The guide states the rate in SARS's own words; it is not the statute. That is a reason the value stays `estimated`.

## Checked and not relied on

- Rates and Monetary Amounts and Amendment of Revenue Laws Bill B34 of 2026 (21 October 2026): amends sections 8 and 23 of the VAT Act, not the rate in section 7. A Bill, not law; not committed.
