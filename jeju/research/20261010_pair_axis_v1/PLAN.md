# Two-horse axis and single-horse anchor ticket study

Status: draft for root approval. This plan fixes the comparison before any new outcome calculations. No result table has been computed for this study.

## Question and interpretation

Using the saved unordered exact-Top3 distribution, do tickets that hold a predicted two-horse Top3 pair or one predicted Top3 horse retain useful Top3 coverage when completed with the remaining horses selected from joint probabilities? The study compares those constrained tickets with unconstrained tickets at the same nominal budget.

The comparison uses both saved distributions from `20261010_joint_relationship_v1`: `matched_baseline` and `candidate`. It reuses the 1,779 races, 17,412 runners, and 269 race dates from 2024-01-05 through 2026-09-19. The 2026 period is partial. This is retrospective development analysis on repeatedly examined labels, not independent future validation.

The outcome is an unordered exact Top3 set. The saved distribution does not model finish order. Whether a selected pair finished exactly first and second, in either order, is a secondary empirical label only; it will not be called a calibrated quinella probability.

## Frozen ticket policies

For each arm, evaluate all five policies at ticket budgets `K ∈ {3, 4}` using that arm's saved full-race distribution `q(S)` over unordered triples `S`. Every race has at least seven runners, so each anchored policy can supply three or four unique tickets throughout the cohort. Also report **only unrestricted top 6** as the original six-ticket reference. Do not compute pair-anchored K=6: a fixed pair has only `N−2` unique completion tickets, so a seven-runner race cannot supply six. Do not duplicate tickets or silently drop those races. No policy uses observed finish labels to select a horse, pair, ticket, cutoff, or ranking.

1. **Unrestricted top K:** take the first `K` triples in saved `canonical_rank` order. This is the maximum predicted-mass reference for that arm and budget.
2. **Top-two marginal pair:** compute each horse's Top3 marginal from `q`; anchor the two horses with the highest marginals, breaking ties by ascending horse number. Among triples containing that pair, take the first `K` in saved `canonical_rank` order. Each completion is the remaining Top3 member, without assigning it third place.
3. **Maximum-joint pair:** choose the pair with the largest `q` mass summed over all triples containing it. Break pair ties by ascending numeric pair. Take the first `K` contained triples in saved `canonical_rank` order. Each completion is the remaining Top3 member, without assigning it third place.
4. **Maximum achievable K-ticket pair mass:** for each pair, sum `q` over its first `K` contained triples in saved `canonical_rank` order. Choose the pair with the largest sum, breaking exact ties by ascending numeric pair; its selected triples are the tickets. This criterion differs from maximizing the pair's total Top3 probability. Each completion is the remaining Top3 member, without assigning it third place.
5. **Single Top3 anchor:** choose the horse with the largest Top3 marginal from `q`, breaking ties by ascending horse number. Among triples containing that horse, take the first `K` in saved `canonical_rank` order. The two other horses are selected together from `q`; they are not independently paired or ranked.

All sums of source probabilities use `math.fsum` in canonical source order. Do not round probabilities or apply a tolerance when ranking. Use the saved `canonical_rank` for unrestricted and contained-triple ranking, verifying it sorts `total_energy` descending and uses canonical numeric triple order only for exact energy ties. The saved probability `q` must be nonincreasing in that order; equal floating-point `q` values do not create a tie if their saved energies differ. Pair-policy score ties use ascending numeric pair; single-horse ties use ascending horse number. These rules preserve the saved unrestricted six-ticket reference, whose existing hit counts are 407 for `matched_baseline` and 423 for `candidate`. That K=6 figure is an original reference, not a same-budget comparison with the anchored policies.

## Outcomes and decomposition

- **K-ticket hit:** at least one selected unordered triple equals the race's observed exact Top3 set.
- **Pair-axis hit:** both anchored horses are in the observed Top3 set. For a selected pair, also record whether those same two horses occupy finish positions 1 and 2 in either order. That exact-Top2 event is secondary and outcome-only.
- **Single-axis hit:** the anchored horse is in the observed Top3 set.
- **Conditional completion:** among races where the pair axis hit, the fraction where a selected ticket completes the observed Top3 set; for a single anchor, the analogous fraction among races where that anchor hit.
- **Failure decomposition:** for pair policies, every ticket miss is either pair-axis miss or pair-axis hit with completion miss. For the single-anchor policy, every miss is either anchor miss or anchor hit with completion miss. Report counts and confirm the components sum to all ticket misses.
- **Mass summaries:** report each selected ticket set's `sum(q)` as predicted probability mass and the observed K-ticket hit. For K=3 and K=4, provide fixed-bin calibration summaries for the primary anchored policies.

The primary full-cohort comparisons are maximum-joint-pair against unrestricted top K within each saved arm at `K=3` and `K=4`. The single-anchor, top-two-marginal-pair, maximum-achievable-pair-mass, and exact-Top2 summaries are secondary exploratory results. Report all five policies for `K=3,4`; report unrestricted K=6 only as the original reference. Include paired date-cluster confidence intervals for primary hit-rate differences, with 2,000 resamples and seed `20261010`; make no multiplicity-adjusted claims. Present both arms separately and do not select a preferred arm based on these labels.

## Confidence and selective summaries

For both arms, confidence summaries cover only **maximum-joint-pair** and **single-Top3-anchor** axes. These are summaries within each arm, not a basis for choosing between arms:

- Pair confidence is the saved `q` probability that both selected pair members occur in the unordered Top3 set. Single-anchor confidence is the saved `q` probability that the selected horse occurs in that set. Report race-level Brier scores and fixed probability bins `[0,.2)`, `[.2,.4)`, `[.4,.6)`, `[.6,.8)`, and `[.8,1]`, with counts, mean predicted probability, and observed axis-hit frequency.
- Also report fixed prediction cutoffs `0.2`, `0.4`, `0.6`, and `0.8` using `confidence >= cutoff`. For each cutoff show selected race count and coverage, observed axis successes, and attached K=3 and K=4 unconditional ticket hits and conditional completion. These are descriptive threshold summaries; no cutoff is selected from observed outcomes.
- Report fixed score-ranked coverage slices of 25%, 50%, 75%, and 100% as retrospective diagnostics. For target coverage `c`, select the first `ceil(c × 1,779)` races after sorting confidence descending and breaking ties by race date and race ID; report the resulting count and realized coverage. A coverage slice does not imply the same future coverage without calibration.
- For the K=3 and K=4 ticket sets of these two policies, bin `sum(q)` with the same fixed probability bins against the exact unordered Top3-set hit. This is descriptive confidence in the selected ticket set, distinct from axis confidence.

Report raw hits divided by all eligible races alongside all conditional rates. Do not present a confidence cutoff or score-ranked subset as an operational guarantee.

## Scope and gates

Use only the saved, immutable inputs pinned in `INPUT_CONTRACT.md`. Read files locally with `.venv/bin/python`; no fitting, database access, network access, source/model/registry edits, or writes to existing research directories. New code and result files, if approved, stay in this new study directory.

Before any outcome calculation, root must approve this plan and input contract. After approval, perform only the integrity checks in the contract, then compute the frozen policies and report. Stop if input hashes, roster, label joins, probability identities, canonical-rank parity, or saved 407/423 six-ticket counts fail; do not repair or substitute sources inside this study.

This ticket analysis does not estimate finish order or exact-Top2 probabilities, does not use market odds, and cannot support returns or an operating-model change. Conclusions must distinguish observed ticket hit rate, axis hit rate, conditional completion, predicted probability mass, and exact-Top2 empirical hit rate.
