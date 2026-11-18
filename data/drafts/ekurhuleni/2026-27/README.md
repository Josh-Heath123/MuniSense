# Ekurhuleni 2026/27: transcribed tariffs

Transcribed by Claude Code in P1-9 from the signed Schedule 2 (`data/sources/ekurhuleni/`, SHA-256 `db55c0d3…7e73`). Every value is `estimated` with the reason "citation check not built until P2" (E29), followed by "scanned page, no text layer" and, where a value is inferred, a note. These are **drafts**: nothing here is reviewed or published (the review-and-publish workflow is P3), which is why they are under `data/drafts/` and not `data/tariffs/`.

| File | Tariff | Basic charge | Energy |
| --- | --- | --- | --- |
| `tariff-b-residential-1-phase.json` | Tariff B (Residential), single-phase | R109.78 per point of supply per month (R1.1, page 4) | R3.3700 per kWh (R.3 and R.4, page 4) |
| `tariff-b-residential-3-phase.json` | Tariff B (Residential), three-phase | R203.89 per point of supply per month (R1.2, page 4) | R3.3700 per kWh |

Tariff B was chosen as the Ekurhuleni example tariff for P1 (E32). It was first described as the tariff of the owner's prepaid meter; that was wrong (E34): the owner's meter is not in Ekurhuleni and its supplier and tariff are unknown.

## Transcription choices

1. **One version per supply phase.** The printed tariff has one basic charge per phase; a customer has one or the other, so each is a version with its own tariff code.
2. **Energy as one flat rate.** The schedule prints a high-demand (June to August) and a low-demand (September to May) value; both are `R3.37,00`. Until seasonal energy exists (P1-12), the rate is one flat rate whose citation names both cells. Bills in both seasons therefore use the same value through the same code path; seasonal behaviour is untested until P1-12, when this becomes a seasonal component with two citations.
3. **`R3.37,00` read as R3.3700.** Inferred from the format and magnitude (P1-8 hazard 2); recorded in the status reason. Confirm against an **Ekurhuleni** vending receipt before `verified` (the owner's receipts are not Ekurhuleni, E34).
4. **End date.** Printed "30 JUNE 2027" (the last day); stored as the exclusive end 2027-07-01, because periods are half-open.
5. **VAT treatment `standard`.** The schedule says only "All tariffs listed below, show VAT excluded." Standard rating is an inference, stated in the status reason.
6. **Rounding policy `ekurhuleni-estimated`.** Not in the schedule. Lines, VAT (once on the subtotal) and total to cents, half up, until learnt from real bills or receipts (P3).
7. **Left out:** the optional internet-based consumption display (R.2, R342.07/month, on request only) and the embedded-generation credit (R.5, needs export metering). Neither applies to a prepaid customer without solar PV.
8. **Applicability.** `applies_to` cites only the first bullet on page 4 (one continuous printed run). The second bullet (not for medium and high voltage), the third (prepayment or post-paid metering) and the fourth (also for internal streetlights, guard houses, booms and gates) are not transcribed as values. The 1-phase and 3-phase versions share the printed name, so a bill shows the phase only through the tariff code.
9. **Prepaid.** The schedule charges the basic charge "per month, per point of supply" but does not say how it is recovered from a prepaid customer (P1-8 hazard 8). That is a question for the prepaid purchase calculation (P1-14, P1-15).
10. **Outside this transcription but on the cited pages:**
    - Page 5, note 3: a customer converting to prepayment, or a new prepayment connection, gets a once-off 40 kWh allocation, "placed as an arrear amount on the prepayment meter account and will be recovered with the first monetary transaction". Affects the first prepaid purchase (P1-14, P1-15).
    - Page 1, general bullets 2 and 3: any penalty or incentive scheme, and any electricity levy imposed by higher authorities, are "in addition to this schedule of tariffs" (levies: P1-11).
    - Page 1, general bullet 4: "The cross-over from existing tariffs to new tariffs will be billed pro rata." A period spanning 1 July 2026 needs pro-rating (P1-13); the engine refuses part months for now.
    - Page 5, note 1: Free Basic Electricity "as specified in the FBE Policy", printed under Tariff B; whether a B customer can receive it is not answered by this schedule.
    - Page 5, note 5: a customer migrated from A.2 may apply for a tariff change after one year (eligibility, not a charge).
