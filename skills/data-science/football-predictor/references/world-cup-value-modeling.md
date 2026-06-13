# World Cup Value Modeling Notes

Use this reference when the user wants World Cup / national-team football predictions focused on 1X2, over/under, and betting value.

## User Target Captured

- Competition scope: World Cup / national-team matches.
- Prediction targets: 1X2, over/under, and betting value.
- Preferred output: concise conclusion, probability table, and whether to bet.
- Current data assumption: historical scores + rankings; odds are used as reference, not necessarily as the only signal.
- Goal: improve hit rate and identify possible value opportunities.

## Recommended Model Stack

Default route:

```txt
Historical scores/rankings
→ Elo-style national-team strength
→ Poisson or Dixon-Coles goal distribution
→ 1X2 + over/under probabilities
→ market-implied probability comparison
→ bet / observe / pass verdict
```

## Why This Stack

- National-team football has sparse, irregular samples; pure ML is likely to overfit early.
- Elo/SPI-style ratings are better for long-term team strength than raw recent goals alone.
- Poisson/Dixon-Coles produces directly useful football markets: scores, 1X2, O/U, BTTS.
- Value betting requires market comparison; model probability alone is not enough.
- Rankings can be used as priors or sanity checks, but should not replace match-level results.

## Practical Output Contract

For each match, prefer this structure:

```txt
结论: 主胜/平/客胜倾向；大/小球倾向；下注/观察/放弃
概率: 主胜 X%, 平 X%, 客胜 X%, 大2.5 X%, 小2.5 X%
价值: 模型概率 vs 市场隐含概率, Edge, 公允赔率, 下注判断
风险: 样本少、阵容/伤停、友谊赛水分、赔率已反映信息
```

## Implementation Notes

- Keep legacy Poisson baseline available for explainability and regression comparison.
- Advanced mode should not require heavy dependencies unless needed; lightweight modules are preferable for CLI usability.
- If using odds, normalize 1X2 implied probabilities to remove overround before comparing edge.
- Treat `可下注` as a value signal, not a certainty signal.
- Add xG, lineup, injuries, travel/rest, and odds movement only after the baseline can be evaluated.

## Pitfalls

- Do not choose a model before clarifying target market and output format.
- Do not use machine learning just because it sounds stronger; data volume and feature quality decide.
- Do not call a bet valuable unless model probability exceeds market-implied probability by a meaningful margin.
- Do not treat FIFA ranking as a calibrated probability model.
