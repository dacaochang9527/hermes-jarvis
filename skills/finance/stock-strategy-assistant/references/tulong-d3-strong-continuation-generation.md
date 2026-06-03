# D3 strong-continuation generation notes

Session signal: after reviewing 0601D3 and 0602D3, the user corrected the workflow: the point is not merely to record a post-hoc `强势延续雷达`; the generator should use yesterday's missed-but-strong samples to improve D1/D2 selection before producing the next D3 watch list.

## Core lesson

Do not treat `强势延续雷达` only as an after-close review bucket. When prior reviews show missed strong continuations, feed the shared features back into the D1/D2 generation path.

The practical split is:

1. `低吸观察` path: D2 has healthy pullback/冲高回落, does not break D1 support, and produces a comfortable buy zone.
2. `强势确认/延续` path: D2 closes near limit-up or otherwise closes strongly near the high, volume ratio is not extreme, and D2 still respects D1 support. These should not be rejected just because they lack pullback.

## Pitfall to avoid

Old generation logic may hard-reject strong D2 continuation as `D2冲高回落特征不足` or penalize it as `D2仍大涨，容易变追高`. That repeats the 0602 issue where strong continuation samples were missed.

When the user asks to apply the new strategy, do not answer that radar can only be checked after D3 close. First update/re-run the D1/D2 selection logic so the next D3 candidate generation can surface comparable strong-continuation samples.

## Implementation pattern

- Add/keep a tested D2 strong-continuation predicate, for example:
  - D2 close is near the limit-up price or D2 pct is strong and close is near high;
  - D2/D1 volume ratio is <= 3;
  - D2 close remains above D1 support.
- Let `is_d2_pullback()` or the D2 gate have two pass paths:
  - pullback path;
  - strong-continuation path.
- In the generator, mark the continuation path explicitly in notes, e.g. `D2强势延续` / `强势确认观察`, and avoid applying low-buy zone rejection blindly.
- Strong continuation may use a confirmation zone around D2 close/high rather than the low-buy `entry_zone(trigger, support)` formula.

## Capacity warning

If low-buy and strong-continuation candidates share one fixed-size watch list, strong continuation can crowd out lower-risk low-buy candidates. Prefer reporting both groups separately or preserving a balanced capacity before cutting a final active watch list.

## Verification

Use TDD for behavior changes:

- Add a failing test where D2 closes at/near limit-up, volume ratio <= 3, and D2 close is above D1 support; expect it to pass with a reason containing `强势延续`.
- Run the focused test first, then the whole suite.
- Re-run D3 generation and compare old/new watch outputs; call out added strong-continuation candidates and displaced low-buy candidates separately.
