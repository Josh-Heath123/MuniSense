# ADR-0011: Add a named pro-rating rounding point and a billing policy for period splitting

- **Status:** Proposed
- **Date:** 2026-11-18 (proposed)
- **Deciders:** Josh Heath (owner)

## Context

A billing period does not always fall inside one calendar month, one season, one tariff version and one VAT rate. A meter-reading period from 15 July to 14 August, a tariff change on 1 July, or a season change on 1 September all need the period split into parts, with monthly values (basic charges, monthly levies, block thresholds, free monthly allocations) and consumption shared between them. The Ekurhuleni 2026/27 schedule says only "The cross-over from existing tariffs to new tariffs will be billed pro rata" (page 1); it does not say how.

Sharing by days produces quotients that do not terminate (R109.78 x 17/31; 300 kWh x 17/31). MuniSense's arithmetic is exact and refuses silent rounding (ADR-0005), so such a quotient must be rounded at a named point. ADR-0005 lists the points (line amount, VAT, total, prepaid kWh allocation) and says "Nothing is quantised anywhere else"; none of them covers pro-rating. Owner decisions: E35 (a new ADR adding a `pro_rating` point) and E38 (billing policies such as pro-rating live in a `BillingPolicy` on the version, separate from rounding).

## Decision

- **A new rounding point, `pro_rating`,** in each `RoundingPolicy`, rounds the **apportioning factors**, which are plain numbers:
  - for a monthly value in a part of a month: days in the part / days in that calendar month;
  - for consumption: days from the period start to the end of a part / days in the whole period (cumulative, so the parts' kWh never go negative and always add up to the total exactly).
  Rounding the unit-free factor, rather than each pro-rated amount, lets one point serve rand charges and kWh thresholds alike; everything computed from a rounded factor is exact and is then rounded at the existing points (line, VAT, total). `None` means "not rounded", which refuses any period whose factors do not terminate.
- **A `BillingPolicy` on each tariff version** names how a period is split and shared, with its own status and evidence (like a rounding policy). P1-13 builds one method for each, and the engine dispatches on the policy's value: monthly values pro-rated **by days** within their calendar month, and consumption shared **by days** across the period. Another method needs a new enum member and the code that implements it. Prepaid policies (block reset, how fixed charges are recovered) join it in P1-14.
- **One share-out per period:** the kWh are shared using the billing policy and `pro_rating` point of the version that covers the period's first day, even if a later version names a different point, so that one rounding applies to the whole share-out.
- **Pro-rating applies only where there is something monthly:** a part with no monthly values for the customer (only daily charges and per-kWh rates) is priced as it is, with no month fraction and no warning.
- **A period is split** at calendar-month starts, version changes, season boundaries and VAT rate changes. Each part is priced on its own (its own version, season, VAT rate and policies); the period's subtotal, VAT and total are the sums of the parts'. A day not covered by a version is refused.
- **Every result that splits or pro-rates warns** while the billing policy is not verified, as for rounding policies. A period result reports the billing and rounding policies used and their weakest statuses separately from the status of the values (as a single bill reports its rounding policy).
- **The new header field** (`billing_policy`) and the new point (`pro_rating`) are added under `schema_version` 1: nothing is stored before P2, so no stored data has the old shape.
- This **adds to ADR-0005's list of points**. Once this ADR is accepted, ADR-0005 is marked "Superseded by ADR-0011" for that list only; everything else in ADR-0005 stands.

## Consequences

- Good: every rounding stays named; period splitting is explainable part by part; the method is named in data with a status, so each supplier's method is visible and can be confirmed or changed per version.
- Bad: suppliers may round differently (for example the pro-rated rand amount to cents rather than the factor, or VAT once on the whole period rather than per part); until real bills confirm the method, results carry a warning and may differ by cents. More parts mean more line roundings.
- Bad, and visible to users: pro-rating by days within each calendar month does not add up to one month of a monthly charge when the months differ in length. A reading period from 15 February to 15 March 2027 charges 14/28 + 14/31 = 0.951613 of a basic charge (0.968854 in 2028). Whether a supplier does this, or pro-rates by the reading period's own length, is exactly what the policy's status says is not yet known.
- Cost now and later: R0.
- Reversibility: easy. The point and the policy are data; another method (for example pro-rating amounts, or VAT on the whole period) is a new option in the policy with its implementation, chosen per supplier.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Round each pro-rated amount at the line point | Uses a point designed for something else; kWh thresholds have no rand step; the rounding would be invisible in the policy |
| A pro-rating point per unit (rand and kWh) | Two points for one decision; the factor already serves both |
| Refuse every period that is not one calendar month | Real meter-reading periods rarely are; the pilot needs them |
| Keep fractions exact and round only at the line point | Non-terminating fractions cannot be held exactly in `Decimal`; would need a fraction type throughout the engine |
