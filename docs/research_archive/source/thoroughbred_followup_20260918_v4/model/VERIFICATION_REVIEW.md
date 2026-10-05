# Independent verification review

An independent reviewer replayed the saved 2026 bundle over all 1,286 races and
13,802 card rows across Busan, Seoul, and Yeongcheon. All 13,802 A probabilities
and all 25,720 stored B/C top-10 rows matched their saved historical predictions,
including keys; the maximum joint-probability invariant error was 1.78e-15.

The reviewer confirmed the frozen unseen-venue win-temperature fallback of 1.0.
For the future export, all 294 rows and 27 races matched source identities and
cutoffs, A was bit-exact against v3 r2, same-date feature invariance passed, and
B/C exclusively used the v4 bundle. No corrected-model defect was found.
