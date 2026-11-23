# Glossary

| Term | Meaning |
| --- | --- |
| **Supplier** | The body that bills the customer for electricity: a municipality (or its utility, such as City Power) or Eskom directly |
| **Tariff** | A named price structure published by a supplier for a customer class, for example Ekurhuleni "Tariff A" |
| **Tariff version** | One tariff's prices for one validity period, such as 1 July 2026 to 30 June 2027. Corrections create new versions |
| **Draft** | A bare tariff version or VAT rate under `data/drafts/`, committed but not published; never used in a calculation; publishing it removes it (ADR-0012) |
| **Supplier catalogue** | `data/catalogue/suppliers.json`: every supplier's code, name, kind and cited tariff-year start month |
| **Source manifest** | `data/sources/<publisher>/sources.json`: the committed source documents of one publisher, by SHA-256, with URL, retrieval date, approval, page count and text layer |
| **Publication** | One committed, immutable file under `data/tariffs/` or `data/vat/`: a tariff version or VAT rate in an envelope that records when it was published (record time) and the publish step's own checks (ADR-0012) |
| **Revision** | The `r<N>` in a publication's id and file name. Every publication takes the next free revision under the date it is filed under; `supersedes` records what it replaces (ADR-0013) |
| **Withdrawal** | A publication with no version: it ends what MuniSense believes about a published version, from its own record time, and puts nothing in its place |
| **Canonical form** | The one byte layout every committed tariff file must have: the JSON written with two-space indentation, non-ASCII characters as themselves and one final newline, keys in the order the file already has |
| **Tariff component** | One typed building block of a tariff: fixed charge, flat energy, block energy, time-of-use energy, demand, capacity, levy, export credit, free basic allocation |
| **Customer class** | Who a tariff applies to: domestic, small business, and so on |
| **Point of supply** | The connection being billed. Fixed charges are usually per point of supply |
| **IBT** | Inclining block tariff: the price per kWh rises as monthly consumption crosses thresholds |
| **Flat tariff** | A single price per kWh, usually with a fixed charge |
| **TOU** | Time-of-use: prices differ by time of day, day type and season |
| **Peak / standard / off-peak** | The three time-of-use periods in Eskom-style tariffs |
| **High-demand / low-demand season** | Eskom's seasons: June to August, and September to May |
| **Demand charge** | A charge per kVA of maximum demand in a billing period |
| **NMD / capacity charge** | Notified maximum demand: a charge based on contracted capacity |
| **FBE** | Free basic electricity: a monthly free allocation (typically 50 kWh) for registered indigent households |
| **SSEG** | Small-scale embedded generation: rooftop solar and similar. May earn export credits |
| **Prepaid** | Electricity bought in advance as tokens. Block thresholds may reset per calendar month |
| **Prepaid purchase** | One token purchase: a rand amount paid and the kWh received. The kWh depend on earlier purchases in the same month, because they decide which blocks are already used |
| **Consumption profile** | How consumption is given to the engine: a period kWh total, kWh used and exported per time-of-use period (`peak`, `standard`, `off_peak`; P4-4), or interval readings (P4-10) |
| **Period total** | The kWh used over a whole billing period (`PeriodTotal`). Called a period total, not a monthly total, because billing periods are not always calendar months |
| **Price basis** | Whether a tariff schedule prints its prices excluding VAT or including VAT. Recorded (and cited) per tariff version |
| **VAT treatment** | How VAT applies to one component's amount: standard-rated, zero-rated or exempt. Recorded (and cited) per component |
| **Season** | Part of the year with its own energy rates (for example a high-demand season June to August). Seasons are a calendar in data with cited dates that must cover every day once (`SeasonalEnergy`, and the TOU calendar's seasons, P4-5) |
| **TOU calendar** | A tariff version's one cited calendar for time of use (`TouCalendar`, ADR-0016): its seasons, and for each season and day type a day schedule |
| **Day type** | How a tariff treats a date for time of use: `weekday`, `saturday` or `sunday` (public holidays may be treated as one of these, P4-6) |
| **Holiday treatment** | A calendar's cited rule for public holidays: each treated as the day of the week it falls on, or a list from the tariff's own document (a coverage window, each listed date treated as a Saturday or a Sunday, and a rule for unlisted holidays); under a list, a day outside the window is refused. The window's end is the first day **not** covered ("to 30 June 2027" is entered as ending on 1 July 2027), unlike a season's end, which is inclusive. A list must cover every day of its version, and at most two years (P4-6) |
| **Time-of-use energy** | An energy charge with a cited rate per kWh for each period of each season of the version's calendar (`TimeOfUseEnergy`, P4-7); priced from kWh used per period, never from a period total |
| **Export credit** | A credit for exported energy with a cited rate per kWh for each period of each season (`ExportCredit`, P4-8). The kWh credited in a period are at most the kWh used in that period in the same calendar month (`BillingPolicy.export_cap`); a bill with exports must cover whole calendar months, and a bill the credit would make negative is refused |
| **Day schedule** | The periods of one day type in one season: cited time ranges in minutes after midnight (SAST), covering the day exactly once, each naming `peak`, `standard` or `off_peak` |
| **Billing policy** | A supplier's named way of applying its tariff to a period: how monthly values are pro-rated for part of a month and how kWh are shared when a period is split (`BillingPolicy`, ADR-0011). Learnt from bills, with its own status |
| **Period splitting** | Pricing a billing period that spans calendar months, tariff versions, seasons or VAT rates as parts, each priced on its own and then added up (`calculate_period`) |
| **Pro-rating** | Scaling a monthly value (a basic charge, a block threshold, a free allocation) for part of a month, by days in the part / days in the month, with the factor rounded at the policy's `pro_rating` point |
| **Prepaid purchase** | A rand amount (as paid, with VAT) turned into kWh, after the kWh bought earlier in the same calendar month, with the same components and policies as a bill (`calculate_purchase`); the kWh are rounded once at the policy's `prepaid_kwh` point |
| **Block reset** | When a prepaid customer's blocks start again; built: on the first day of each calendar month (`BillingPolicy.block_reset`) |
| **Levy** | A charge imposed by a higher authority that a schedule adds to its own tariffs (for example "in addition to this schedule of tariffs"); priced per kWh, per day or per month (`Levy`) |
| **Free basic allocation** | Free kWh per calendar month for an eligible customer (Free Basic Electricity); eligibility is an input, never inferred. Shown as credit lines at the energy's own rates (`FreeBasicAllocation`) |
| **Line item** | One charge or credit on a calculated bill (a fixed charge, flat energy, one block, a levy, or a credit for free kWh; a credit has a negative amount, minus rate x quantity), with its quantity, printed rate, amount and the citation of every value it used, by role (rate, lower and upper threshold, label, VAT treatment, free allowance, season dates, season label) |
| **VAT-able subtotal** | The sum of the standard-rated line amounts; zero-rated and exempt lines are left out |
| **Billing period** | The dates a bill covers, as a half-open range: from the start date up to, but not including, the end date |
| **Credit meter** | Conventional metered supply billed in arrears |
| **NERSA** | National Energy Regulator of South Africa. Approves municipal electricity tariff increases annually |
| **MFMA** | Municipal Finance Management Act. Section 75 requires budget and tariff documents to be published on the municipal website |
| **Valid time** | When a tariff applies in the real world |
| **Record time** | When MuniSense recorded or superseded a fact. With valid time, this gives two timelines ("bitemporal") |
| **Provenance** | Where a value came from: source document, page, table, retrieval date and hash |
| **Verification status** | `verified` (printed text found verbatim on the cited page by a deterministic check, plus a recorded verifier, method and date; ADR-0006), `estimated` (with a reason), `user_provided` (with who provided it) |
| **Golden bill** | A real or official example bill, anonymised to figures, that the engine must reproduce. For prepaid, a golden case is a whole month of purchases, not a single receipt |
| **Rounding policy** | A supplier's rule for rounding: per line or per bill, to cents or rands, half-up or half-even |
| **Gate** | The end-of-phase review: report, architect review, owner approval |
