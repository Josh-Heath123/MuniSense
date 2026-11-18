# Glossary

| Term | Meaning |
| --- | --- |
| **Supplier** | The body that bills the customer for electricity: a municipality (or its utility, such as City Power) or Eskom directly |
| **Tariff** | A named price structure published by a supplier for a customer class, for example Ekurhuleni "Tariff A" |
| **Tariff version** | One tariff's prices for one validity period, such as 1 July 2026 to 30 June 2027. Corrections create new versions |
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
| **Consumption profile** | How consumption is given to the engine: a period kWh total, kWh per time-of-use bucket (from P4), or (later) interval data |
| **Period total** | The kWh used over a whole billing period (`PeriodTotal`). Called a period total, not a monthly total, because billing periods are not always calendar months |
| **Price basis** | Whether a tariff schedule prints its prices excluding VAT or including VAT. Recorded (and cited) per tariff version |
| **VAT treatment** | How VAT applies to one component's amount: standard-rated, zero-rated or exempt. Recorded (and cited) per component |
| **Season** | Part of the year with its own energy rates (for example a high-demand season June to August). Seasons are a calendar in data with cited dates that must cover every day once (`SeasonalEnergy`) |
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
