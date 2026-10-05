# Legacy algorithm reuse review

The v2 feature pipeline reviewed `src/horse_racing/analysis/features/ability.py`,
`src/horse_racing/analysis/features/speed_figure.py`, and
`docs/ABILITY_V2_NO_RATING.md`.  It reuses their published algorithmic ideas,
but it does not claim to reproduce a legacy champion score or model artifact.
Those artifacts depend on their own frame contracts, source schemas, and
training profiles, which are outside this bounded run.

## Elo

Reused without tuning:

- multiplayer Elo based on the fraction of valid opponents beaten, with ties
  worth one half;
- prior 1500, global K=32, context K=28, and 730-day half-life decay;
- output of the pre-race state and update only after all races on a date.

Adapted for the unified Thoroughbred contract:

- official horse IDs stay strings rather than being coerced to integers;
- context is exact `venue_code` and exact `distance_m`, while the legacy module
  uses venue and broad short/middle/long distance bands;
- cancelled, DNF, disqualified, scratched, and excluded rows never enter the
  Elo comparison.  A race is updated only from its valid ranked finishers;
- current-card relative differences are computed after all runners receive
  their pre-card states.

## Speed figure

Reused without outcome tuning:

- course and exact-distance robust top-three par from a strictly prior 730-day
  window;
- matching-going par threshold 12 and fallback course-distance threshold 20;
- historical venue-day variant requiring three races, bounded to ±0.06 log
  units;
- `100*log(speed/par)`, ±10 clipping, and the -4 lower censor for slow tail
  finishes from the 60th finish percentile;
- last, average-three, median/best-five, trend, count, censor rate, and exact
  distance summaries.

Adapted for this source:

- the unified table supplies seconds (`race_time_s`) rather than milliseconds;
- the supported source is Thoroughbred Seoul, Busan, and Yeongcheon, so valid
  speeds are bounded to 10–20 m/s;
- invalid or missing source times remain unavailable and are listed in
  `invalid_speed_source_audit.csv`; zero is never substituted;
- historical same-day results may jointly estimate that completed day's track
  variant, but the observation enters horse history only after the date and is
  never visible to another target on that date.

## Form and relative features

These are new bounded additions rather than a legacy-score reproduction.
Recent percentiles and win/top-three counts use only valid ranked finishes;
DNF history uses confirmed starts and is separate.  Burden and distance deltas
refer to the last confirmed prior start.  Field-relative Elo, rating, and speed
use only the current scheduled card and already-computed pre-card values.

All constants were declared in code before model comparison.  Feature research
does not use target outcomes to tune a cutoff, prior, or transformation.
