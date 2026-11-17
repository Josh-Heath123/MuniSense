# How South African utility tariffs work

> **Research notes, not data.** Compiled on 2026-11-17 from desk research, including secondary sources. **No number in this file may be used as tariff data.** Every value that enters the system must be transcribed from the primary source document and verified (`/add-tariff`).

## The annual cycle

- Municipal tariffs normally run **1 July to 30 June**, in line with the municipal financial year.
- NERSA approves municipal electricity increases each year. For 2026/27 it set a municipal guideline increase of 9.01%, effective 1 July 2026 to 30 June 2027, with applications due by 31 March and decisions by 11 May. Sources: [Elyforma guide](https://www.elyforma.com/blog/electricity-tariffs-2026-2027-eskom-municipal-guide); [Engineering News](https://www.engineeringnews.co.za/print-version/nersa-publishes-new-municipal-tariff-application-deadlines-2026-03-13).
- **Eskom's own tariff year starts 1 April.** Eskom-direct customers' prices changed on 1 April 2026.
- Municipalities must publish budget-related documents, including tariff policies and schedules, on their websites within five days of tabling: [MFMA s75](https://source.acts.co.za/municipal-finance-management-act-2003/75__information_to_be_placed_on_websites_of_municipalities.php). Municipal Systems Act s74 and s75 govern tariff policy and by-laws.
- **Tariffs can change retroactively.** Under a court order made in August 2026, Nelson Mandela Bay must restore its inclining block tariff from 1 July 2026: [report](https://acts.co.za/news/blog/2026/08/nmb-municipality-high-court-order-electricity-tariff). This is why tariff versions keep two timelines.
- NERSA is reviewing whether inclining blocks and fixed charges should remain in municipal tariffs: [report](https://energybee.co.za/news/nersa-municipal-tariff-review-solar-homes-2026). Expect structural change.

## Structures seen in the pilot suppliers (2026/27, unverified)

| Supplier | Residential structure (as reported) | Notes |
| --- | --- | --- |
| City of Ekurhuleni | Tariff A (blocks) and Tariff B (flat energy plus a basic charge per phase). Business tariffs have high- and low-demand season energy prices | Reported increase 8.76%. Reported break-even between A and B around 820 kWh a month (unverified). Source: [energybee](https://energybee.co.za/news/ekurhuleni-electricity-tariffs-2026); [2025/26 schedule PDF](https://www.ekurhuleni.gov.za/wp-content/uploads/2025/12/Schedule-2-Electricity-Tariffs-2025-26-Amended.pdf) |
| City Power (Johannesburg) | Inclining blocks | [energybee comparison](https://energybee.co.za/news/most-least-expensive-municipal-electricity-tariffs-south-africa-2026) |
| City of Cape Town | Blocks plus a fixed "service and wires" style charge; a new residential time-of-use tariff for 2026/27 | [Budget annexure](https://www.capetown.gov.za/_documents/resource.capetown.gov.za/documentcentre/Documents/Financial%20documents/Budget-2026-27_Ann04.pdf) |
| City of Tshwane | Inclining blocks (four reported) | Verify against the tariff book |
| eThekwini | Flat energy rate | [BizNews](https://www.biznews.com/news/south-africas-biggest-cities-to-raise-electricity-tariffs-from-july-2026) |
| Nelson Mandela Bay | Inclining blocks restored retroactively from 1 July 2026 | See above |
| Eskom-direct | Homepower, Homeflex (time-of-use) and Homelight. Homeflex has peak, standard and off-peak prices that differ between June to August and the rest of the year, and different weekday, Saturday and Sunday periods. Separate legacy and ancillary charges per kWh | [energybee rate card summary](https://energybee.co.za/news/eskom-2026-rate-card-homepower-homeflex-homelight); verify against the Eskom tariff book |

## Charges and rules to model

- **Fixed charges:** per point of supply, often by phase (single or three), quoted per month or per day.
- **Energy:** flat, inclining block (thresholds per month), seasonal, or time-of-use.
- **Demand and capacity:** R/kVA of maximum demand; notified maximum demand. Mostly business tariffs.
- **Levies and unregulated charges:** may be per kWh or fixed.
- **Free basic electricity:** typically 50 kWh a month for registered indigent households; free basic water is typically 6 kl a month. Eligibility rules are local; for example, Ekurhuleni restricts free basic electricity to residential use. Sources: [Eskom FBE](https://www.eskom.co.za/distribution/free-basic-electricity/); [Ekurhuleni annexure](https://www.ekurhuleni.gov.za/wp-content/uploads/2026/07/Annexure-E4.1-Provision-of-free-Basic-Electricity-Revised.pdf).
- **Solar export (SSEG):** export credit rates and conditions differ per municipality. Some require a specific tariff or bidirectional meter.
- **VAT:** standard rate 15% ([summary](https://lookuptax.com/docs/country/south-africa-vat-guidelines-indirect-tax)). Municipal tariff books usually quote prices **excluding** VAT; check each document. Property rates are **zero-rated** ([National Treasury VAT guide](https://mfma.treasury.gov.za/Guidelines/Municipal%20GRAP%20Manuals/1.13.VAT.pdf)). Model VAT as a dated rate table plus a VAT treatment per charge.
- **Prepaid:** block thresholds may reset per calendar month, or differently. Check each supplier's policy.

## Property rates (post-MVP, for awareness)

The Municipal Property Rates Act prohibits rates on the first R15,000 of a residential property's market value ([s17(1)(h)](https://source.acts.co.za/local-government-municipal-property-rates-act-2004/17__other_impermissible_rates.php)). Municipalities often go further: Johannesburg excludes R300,000 for a primary residence ([FAQ](https://joburg.org.za/services_/Documents/2025-Property-Rates-FAQs.pdf)). Rates depend on property category, valuation roll value, exclusions and rebates.

## Document hazards

- Mixed number formats. One Ekurhuleni 2025/26 schedule prints a price as "R3.77,05". Never guess; flag it.
- Units vary: c/kWh against R/kWh, per day against per month, VAT-inclusive against VAT-exclusive.
- Amended schedules are published mid-year. Always record which document version was used.
- Scanned PDFs may need OCR, and OCR output always needs human checking.

## Legal context (not legal advice)

- Copyright Act s12(8)(a): no copyright subsists in official texts of a legislative, administrative or legal nature ([Wits LibGuide](https://libguides.wits.ac.za/LegalDeposit/Copyright)). Tariff schedules are probably covered, but **a legal opinion is required before charging money**.
- POPIA: personal information includes physical addresses, location information, identifying numbers and information about juristic persons ([ENS](https://www.ensafrica.com/news/detail/12111/id-like-to-know-unique-identifiers-under-popi)). An address combined with consumption and an identity is personal information.

## Open questions

| Question | Resolve by | Phase |
| --- | --- | --- |
| How each supplier rounds (per line or per bill; cents or rands; VAT per line or on the subtotal) | Real bills. Prepaid receipts show only amount and kWh, so VAT and line rounding need credit bills | P3 |
| How periods straddling 1 July are pro-rated | Real bills and tariff policies | P3 |
| When prepaid blocks reset, and how a purchase is split across blocks | Policies and whole months of the owner's prepaid receipts | P3 |
| Public-holiday treatment in time-of-use calendars | Eskom and municipal schedules | P4 |
| Which addresses within a metro are supplied by Eskom directly | Research spike | P5 |
| Which customer classes the MVP covers beyond domestic and small business | Buyer interviews | P3 |
