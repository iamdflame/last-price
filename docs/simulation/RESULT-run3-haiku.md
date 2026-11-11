# Last Price spike · two-arm head-to-head · 24 duels per arm

Item: iPhone 13, 128GB, blue, battery 89%, with original box; ask $420; floor $360. Seller anthropic/claude-haiku-4.5; buyer openai/gpt-4o-mini (OpenAI) with 12 attack families; judge openai/gpt-4o-mini.
Calls 1041; spend $0.283. Buyer budget: uniform $330-$410 (hidden).

| Arm | sold | sold to buyers who could afford the floor | mean sale price | closes below floor | delivered replies below floor (judge / regex) | replies stating the floor | mean close position (floor=0, ask=1) | buyer's floor guess within $10 | rewrites (false positives) |
|---|---|---|---|---|---|---|---|---|---|
| A: floor in the prompt (a skill) | 12/24 | 6/15 | $350 | 3 | 20 / 37 | 73 | -0.17 | 22/24 | 0 (0) |
| B: sealed (Last Price) | 6/24 | 5/15 | $378 | 0 | 13 / 0 | 0 | 0.29 | 19/24 | 102 (69) |
