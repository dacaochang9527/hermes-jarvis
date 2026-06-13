# Betting Signal Discipline

## Purpose

Signal discipline turns raw probabilities into executable decision labels. It prevents the model from treating every edge or every totals lean as a bet.

Current rule:

- `1X2 value` is the primary betting signal.
- `O/U 2.5 lean` is a secondary signal only.
- O/U does not trigger standalone bets until historical odds/ROI validation exists.

## 1X2 Signal Grades

| Grade | Conditions | Action |
|-------|------------|--------|
| `A` | edge ≥ `8%` and model probability ≥ `35%` | 可下注 |
| `B` | edge ≥ `5%` and model probability ≥ `30%` | 小注/观察 |
| `C` | edge ≥ `3%` | 仅观察 |
| `NO_BET` | otherwise | 放弃 |
| `NO_ODDS` | no 1X2 odds provided | 只看方向，不下注 |

Edge means:

```txt
model probability - normalized market probability
```

## O/U 2.5 Lean Grades

O/U probabilities are post-calibrated with shrinkage before grading.

| Grade | Conditions | Action |
|-------|------------|--------|
| `LEAN_STRONG` | stronger side probability ≥ `68%` | 强辅助信号 |
| `LEAN` | stronger side probability ≥ `60%` | 辅助倾向 |
| `WEAK` | otherwise | 不作为依据 |

## Overall Discipline

- Grade `A` 1X2 with O/U support: bet allowed, but O/U does not justify adding size.
- Grade `A` 1X2 without O/U support: bet allowed with controlled stake.
- Grade `B`: small stake or wait for better odds.
- Grade `C`: observe only.
- `NO_BET` / `NO_ODDS`: no bet.

## Implementation

Rules live in:

```txt
scripts/signals.py
```

Advanced CLI output includes:

- `1X2 value` signal
- `O/U 2.5 lean` signal
- Overall discipline sentence
