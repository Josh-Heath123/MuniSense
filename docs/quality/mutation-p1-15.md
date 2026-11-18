# Mutation testing: `domain.billing` (P1-15)

Run on 2026-11-18 with mutmut 3.8.1 (configuration in `pyproject.toml`, `[tool.mutmut]`): every function in `src/munisense/domain/billing/` mutated, each mutant tested against the domain and data tests (`tests/unit/domain/`, `tests/property/domain/`, `tests/unit/data/`).

| Result | Count |
| --- | --- |
| Mutants | 1,530 |
| Killed | 1,379 |
| Timed out (counted as caught: an infinite loop) | 1 |
| Survived | 150 |
| **Score (caught / all)** | **90.2%** (target: at least 80%) |

The first run left 186 survivors (87.8%). Reviewing them, and a code review of that review, found 36 surviving mutants that tests should catch; about 20 new tests now kill them (see the P1-15 pull request): a period across the year end; a free allowance scaled on a flat tariff; the split flag without monthly values; a version ending on the period's start; season cuts limited to their own version; a period whose last day starts a season; the "1 month" and "all kWh" descriptions; a purchase on the version's last day; eligibility passed to prepaid fixed charges; header and VAT statuses in a purchase; kWh below 1 with no purchase; a monthly levy as the only fixed charge; zero purchases on free energy, on a free first block and without a rounding point; the sources of the open last block; a seasonal period ending in year 9999.

## Every survivor, reviewed

### Message text only (120)

These change only the text of an error or warning message (or blank it), not which error or warning is raised. Tests assert the error type or warning code, which is what callers act on; the wording is for people. Not worth a test each.

| Function | Survivors |
| --- | --- |
| `consumption.x_require_period_total` | 2 |
| `engine.x__check_calculable` | 12 |
| `engine.x__check_eligibility` | 11 |
| `engine.x__seasons` | 4 |
| `engine.x__warnings` | 11 |
| `engine.x__words` | 2 |
| `engine.x_check_price_basis` | 5 |
| `prepaid.x__check` | 15 |
| `prepaid.x__check_purchase` | 9 |
| `prepaid.x__check_whole_steps` | 2 |
| `prepaid.x__fixed_charges` | 6 |
| `prepaid.x__warnings` | 10 |
| `prepaid.x_calculate_month` | 8 |
| `prepaid.x_calculate_purchase` | 2 |
| `prepaid.xǁ_Walkǁfinish` | 5 |
| `splitting.x__check_versions` | 12 |
| `splitting.x__warnings` | 4 |

<details><summary>All names</summary>

- `consumption.x_require_period_total__mutmut_2`
- `consumption.x_require_period_total__mutmut_3`
- `engine.x__check_calculable__mutmut_7`
- `engine.x__check_calculable__mutmut_8`
- `engine.x__check_calculable__mutmut_9`
- `engine.x__check_calculable__mutmut_10`
- `engine.x__check_calculable__mutmut_20`
- `engine.x__check_calculable__mutmut_21`
- `engine.x__check_calculable__mutmut_22`
- `engine.x__check_calculable__mutmut_23`
- `engine.x__check_calculable__mutmut_24`
- `engine.x__check_calculable__mutmut_25`
- `engine.x__check_calculable__mutmut_26`
- `engine.x__check_calculable__mutmut_27`
- `engine.x_check_price_basis__mutmut_2`
- `engine.x_check_price_basis__mutmut_3`
- `engine.x_check_price_basis__mutmut_4`
- `engine.x_check_price_basis__mutmut_5`
- `engine.x_check_price_basis__mutmut_6`
- `engine.x__check_eligibility__mutmut_3`
- `engine.x__check_eligibility__mutmut_4`
- `engine.x__check_eligibility__mutmut_5`
- `engine.x__check_eligibility__mutmut_6`
- `engine.x__check_eligibility__mutmut_10`
- `engine.x__check_eligibility__mutmut_11`
- `engine.x__check_eligibility__mutmut_12`
- `engine.x__check_eligibility__mutmut_13`
- `engine.x__check_eligibility__mutmut_14`
- `engine.x__check_eligibility__mutmut_15`
- `engine.x__check_eligibility__mutmut_16`
- `engine.x__seasons__mutmut_12`
- `engine.x__seasons__mutmut_13`
- `engine.x__seasons__mutmut_14`
- `engine.x__seasons__mutmut_15`
- `engine.x__words__mutmut_5`
- `engine.x__words__mutmut_6`
- `engine.x__warnings__mutmut_7`
- `engine.x__warnings__mutmut_8`
- `engine.x__warnings__mutmut_9`
- `engine.x__warnings__mutmut_10`
- `engine.x__warnings__mutmut_11`
- `engine.x__warnings__mutmut_12`
- `engine.x__warnings__mutmut_13`
- `engine.x__warnings__mutmut_21`
- `engine.x__warnings__mutmut_22`
- `engine.x__warnings__mutmut_29`
- `engine.x__warnings__mutmut_30`
- `prepaid.x_calculate_purchase__mutmut_36`
- `prepaid.x_calculate_purchase__mutmut_37`
- `prepaid.x_calculate_month__mutmut_8`
- `prepaid.x_calculate_month__mutmut_9`
- `prepaid.x_calculate_month__mutmut_10`
- `prepaid.x_calculate_month__mutmut_11`
- `prepaid.x_calculate_month__mutmut_14`
- `prepaid.x_calculate_month__mutmut_15`
- `prepaid.x_calculate_month__mutmut_16`
- `prepaid.x_calculate_month__mutmut_17`
- `prepaid.x__check__mutmut_3`
- `prepaid.x__check__mutmut_4`
- `prepaid.x__check__mutmut_5`
- `prepaid.x__check__mutmut_6`
- `prepaid.x__check__mutmut_12`
- `prepaid.x__check__mutmut_13`
- `prepaid.x__check__mutmut_14`
- `prepaid.x__check__mutmut_15`
- `prepaid.x__check__mutmut_16`
- `prepaid.x__check__mutmut_17`
- `prepaid.x__check__mutmut_18`
- `prepaid.x__check__mutmut_19`
- `prepaid.x__check__mutmut_20`
- `prepaid.x__check__mutmut_21`
- `prepaid.x__check__mutmut_22`
- `prepaid.x__check_purchase__mutmut_3`
- `prepaid.x__check_purchase__mutmut_4`
- `prepaid.x__check_purchase__mutmut_5`
- `prepaid.x__check_purchase__mutmut_6`
- `prepaid.x__check_purchase__mutmut_12`
- `prepaid.x__check_purchase__mutmut_13`
- `prepaid.x__check_purchase__mutmut_14`
- `prepaid.x__check_purchase__mutmut_15`
- `prepaid.x__check_purchase__mutmut_16`
- `prepaid.x__fixed_charges__mutmut_34`
- `prepaid.x__fixed_charges__mutmut_35`
- `prepaid.x__fixed_charges__mutmut_36`
- `prepaid.x__fixed_charges__mutmut_37`
- `prepaid.x__fixed_charges__mutmut_38`
- `prepaid.x__fixed_charges__mutmut_39`
- `prepaid.x__check_whole_steps__mutmut_5`
- `prepaid.x__check_whole_steps__mutmut_7`
- `prepaid.xǁ_Walkǁfinish__mutmut_6`
- `prepaid.xǁ_Walkǁfinish__mutmut_7`
- `prepaid.xǁ_Walkǁfinish__mutmut_8`
- `prepaid.xǁ_Walkǁfinish__mutmut_9`
- `prepaid.xǁ_Walkǁfinish__mutmut_10`
- `prepaid.x__warnings__mutmut_12`
- `prepaid.x__warnings__mutmut_13`
- `prepaid.x__warnings__mutmut_14`
- `prepaid.x__warnings__mutmut_15`
- `prepaid.x__warnings__mutmut_26`
- `prepaid.x__warnings__mutmut_27`
- `prepaid.x__warnings__mutmut_28`
- `prepaid.x__warnings__mutmut_29`
- `prepaid.x__warnings__mutmut_36`
- `prepaid.x__warnings__mutmut_37`
- `splitting.x__check_versions__mutmut_2`
- `splitting.x__check_versions__mutmut_3`
- `splitting.x__check_versions__mutmut_4`
- `splitting.x__check_versions__mutmut_5`
- `splitting.x__check_versions__mutmut_9`
- `splitting.x__check_versions__mutmut_10`
- `splitting.x__check_versions__mutmut_11`
- `splitting.x__check_versions__mutmut_12`
- `splitting.x__check_versions__mutmut_24`
- `splitting.x__check_versions__mutmut_25`
- `splitting.x__check_versions__mutmut_26`
- `splitting.x__check_versions__mutmut_27`
- `splitting.x__warnings__mutmut_8`
- `splitting.x__warnings__mutmut_10`
- `splitting.x__warnings__mutmut_16`
- `splitting.x__warnings__mutmut_17`

</details>

### Equivalent (30)

These cannot change a result's value; no test asserting values can tell them from the original. Two keep the value but change its representation (noted), which matters only once kWh are serialised (P5).

| Mutant | Change | Why |
| --- | --- | --- |
| `consumption.x__no_negative_zero__mutmut_2` | `return value.copy_abs() if value.is_zero() else value` → `return value.copy_abs() if (value.is_zero()) or True else value` | `copy_abs` on every value: kWh are validated non-negative first, so only negative zero changes, which is the function's purpose |
| `engine.x__blocks__mutmut_56` | `lower = upper if upper is not None else lower` → `lower = upper if (upper is not None) or True else lower` | after the open last block the loop ends, so the updated lower bound is never read |
| `engine.x__apply_vat__mutmut_18` | `…in zip(lines, taxable, strict=True)` → `…in zip(lines, taxable, strict=None)` | `zip` of two lists of the same length by construction; `strict` cannot change the result |
| `engine.x__apply_vat__mutmut_21` | `…axable in zip(lines, taxable, strict=True)` → `…axable in zip(lines, taxable, )` | `zip` of two lists of the same length by construction; `strict` cannot change the result |
| `engine.x__apply_vat__mutmut_22` | `…in zip(lines, taxable, strict=True)` → `…in zip(lines, taxable, strict=False)` | `zip` of two lists of the same length by construction; `strict` cannot change the result |
| `engine.x__apply_vat__mutmut_29` | `…in zip(lines, taxable, strict=True) if is_taxable` → `…in zip(lines, taxable, strict=None) if is_taxable` | `zip` of two lists of the same length by construction; `strict` cannot change the result |
| `engine.x__apply_vat__mutmut_32` | `…axable in zip(lines, taxable, strict=True) if is_taxable` → `…axable in zip(lines, taxable, ) if is_taxable` | `zip` of two lists of the same length by construction; `strict` cannot change the result |
| `engine.x__apply_vat__mutmut_33` | `…in zip(lines, taxable, strict=True) if is_taxable` → `…in zip(lines, taxable, strict=False) if is_taxable` | `zip` of two lists of the same length by construction; `strict` cannot change the result |
| `prepaid.x_calculate_purchase__mutmut_20` | `case unknown:  # pragma: no cover  # every member is handled above` → `(line removed)` | unreachable `assert_never` arm: every enum member is handled above |
| `prepaid.x_calculate_purchase__mutmut_21` | `assert_never(unknown)` → `assert_never(None)` | unreachable `assert_never` arm: every enum member is handled above |
| `prepaid.x_calculate_month__mutmut_47` | `…(purchases=so_far.purchases + 1, kwh=purchase.month_kwh_after)` → `…(purchases=so_far.purchases + 2, kwh=purchase.month_kwh_after)` | the purchase count is only ever compared with zero, so counting by two changes nothing |
| `prepaid.xǁ_Walkǁ_rounded__mutmut_2` | `return kwh if self.point is None else self.point.apply(kwh)` → `return kwh if (self.point is None) or True else self.point.apply(kwh)` | equal in value, representation differs: with a point set the whole segments are already whole steps, so not rounding them keeps the value (e.g. `50` instead of `50.00`) |
| `prepaid.x__sources__mutmut_22` | `…locks[index - 1].up_to_kwh if index > 0 else None` → `…locks[index - 1].up_to_kwh if (index > 0) or True else None` | for the first block `blocks[-1]` is the open last block, whose threshold is `None`: the same as no lower threshold |
| `prepaid.x__sources__mutmut_25` | `…ndex - 1].up_to_kwh if index > 0 else None` → `…ndex - 1].up_to_kwh if index >= 0 else None` | for the first block `blocks[-1]` is the open last block, whose threshold is `None`: the same as no lower threshold |
| `splitting.x_calculate_period__mutmut_46` | `… in zip(parts, shares, strict=True)` → `… in zip(parts, shares, strict=None)` | `zip` of two lists of the same length by construction; `strict` cannot change the result |
| `splitting.x_calculate_period__mutmut_49` | `…n), kwh in zip(parts, shares, strict=True)` → `…n), kwh in zip(parts, shares, )` | `zip` of two lists of the same length by construction; `strict` cannot change the result |
| `splitting.x_calculate_period__mutmut_50` | `… in zip(parts, shares, strict=True)` → `… in zip(parts, shares, strict=False)` | `zip` of two lists of the same length by construction; `strict` cannot change the result |
| `splitting.x__split__mutmut_8` | `…ges(version) if period.start < d < period.end}` → `…ges(version) if period.start <= d < period.end}` | re-adds a date that is already a cut: the period's own start or end |
| `splitting.x__split__mutmut_9` | `…version) if period.start < d < period.end}` → `…version) if period.start < d <= period.end}` | re-adds a date that is already a cut: the period's own start or end |
| `splitting.x__split__mutmut_25` | `…if rate.end and period.start < rate.end < period.end` → `…if rate.end and period.start <= rate.end < period.end` | re-adds a date that is already a cut: the period's own start or end |
| `splitting.x__split__mutmut_26` | `… and period.start < rate.end < period.end` → `… and period.start < rate.end <= period.end` | re-adds a date that is already a cut: the period's own start or end |
| `splitting.x__month_starts__mutmut_23` | `if first >= period.end:` → `if first > period.end:` | re-adds a date that is already a cut: the period's own start or end |
| `splitting.x__season_starts__mutmut_22` | `start = date(year, 3, 1)  # without 29 February the season starts on 1` → `start = date(year, 4, 1)  # without 29 February the season starts on 1` | a season starting on 29 February starts on 1 March in other years, which is always a calendar-month start and so already a cut |
| `splitting.x__season_starts__mutmut_31` | `if period.start < start < period.end:` → `if period.start <= start < period.end:` | re-adds a date that is already a cut: the period's own start or end |
| `splitting.x__season_starts__mutmut_32` | `if period.start < start < period.end:` → `if period.start < start <= period.end:` | re-adds a date that is already a cut: the period's own start or end |
| `splitting.x__shares__mutmut_3` | `case unknown:  # pragma: no cover  # every member is handled above` → `(line removed)` | unreachable `assert_never` arm: every enum member is handled above |
| `splitting.x__shares__mutmut_12` | `assert_never(unknown)` → `assert_never(None)` | unreachable `assert_never` arm: every enum member is handled above |
| `splitting.x__shares_by_days__mutmut_7` | `if index == len(parts) - 1:` → `if index == len(parts) + 1:` | equal in value, representation differs: the last part's cumulative factor is days/days = 1.000000, so computing it gives the total (e.g. `27.096780` instead of `27.09678`) |
| `splitting.x__month_fraction__mutmut_9` | `case unknown:  # pragma: no cover  # every member is handled above` → `(line removed)` | unreachable `assert_never` arm: every enum member is handled above |
| `splitting.x__month_fraction__mutmut_22` | `assert_never(unknown)` → `assert_never(None)` | unreachable `assert_never` arm: every enum member is handled above |

## How to re-run

`uv run mutmut run`, then `uv run mutmut results`. Results are cached by source: after changing only tests, re-run named mutants with `uv run mutmut run <names>`. The working copy `mutants/` is git-ignored. Not part of `poe verify` or CI: a full run takes about four minutes here.
