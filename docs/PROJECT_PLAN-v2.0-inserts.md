# v2.0 paste-ready edits

Companion to `docs/decisions/v2.0-cycling-domain.md`. Four blocks:
(1) new plan section, (2) §3 replacements, (3) Revisions summary for
`docs/PROJECT_PLAN.md` (the v1.5+ convention), (4) CLAUDE.md scope
constraints. Apply after approving the addendum.

---

## Block 1 — New section for docs/PROJECT_PLAN.md: "Cycling Domain Phases"

## Phase C1 — Rides Core Models (Release 2.0 begins)

**Objective:** Model the rides already ingested. No new API calls.

### Tasks

* [ ] Extend the weather-eligible activity selection to D23 ride types
      (outdoor, with coordinates); `VirtualRide` and trainer rides stay
      permanently unmatched with NULL weather.
* [ ] `int_rides_with_weather` — one row per D23 ride, nearest-hour
      match per the existing D7/60-minute rules.
* [ ] `int_ride_measures` — derived measures (distance mi, moving and
      elapsed time, average speed mph, avg HR, avg cadence, calendar
      fields) and the D25 validity ladder with exclusion reasons.
* [ ] `fct_rides` — core projection, one row per D23 ride.
* [ ] Marts: `mart_weekly_cycling` (weekly mileage, moving time, ride
      count, avg speed, avg cadence, avg HR, avg temperature context,
      sufficiency flag at ≥ 2 valid rides — the D12 spirit) and
      `mart_ride_quality` (ride grain with validity and exclusion
      reasons — the `mart_run_quality` mirror).
* [ ] App: **Cycling training** view (weekly volume, average speed,
      cadence, HR, temperature context). Allow-list +2, red first.

### Acceptance criteria

1. Running-side output is byte-identical (verification check 1).
2. One row per D23 ride; e-bike types absent; indoor flagged.
3. Every invalid ride carries an exclusion reason.
4. Weekly sufficiency flips exactly at the threshold.

**Estimated effort:** 1 weekend

## Phase C2 — Segment Efforts (completes Release 2.0)

**Objective:** Ingest segment efforts and answer the cycling primary
question's data layer.

### Tasks

* [ ] Ingestion per D24: detail fetch, three raw tables, resumable
      status rows, batch cap, exit-3 contract, `sync-segment-efforts`
      CLI and Make target, sync-state watermark.
* [ ] Staging: `stg_strava__segment_efforts` (effort grain: elapsed and
      moving time s, avg HR, avg cadence, start date, PR rank),
      `stg_strava__segments` (segment grain: name, distance m, average
      grade, start/end coordinates, city/state).
* [ ] Core: `fct_segment_efforts` — one row per effort on a D23
      non-virtual ride; virtual efforts flagged and held out of marts
      (D28).
* [ ] Mart: `mart_segment_trend` — segment × effort with rolling
      5-effort median, cumulative best, effort count, sufficiency flag
      (≥ 5), `short_segment` flag (< 120 s median duration), HR,
      cadence, and matched weather context from the parent ride.
* [ ] App: **Cycling segments** view — per-segment trend chart
      (efforts as points, rolling median as the only line, cumulative
      best as reference), segment picker limited to sufficient
      segments, short-segment caveat displayed. Allow-list +1, red
      first.

### Acceptance criteria

1. Re-running ingestion converges (no duplicates; failed retried;
   success/unavailable terminal).
2. Spot check: one segment's effort count and times match the Strava
   My Results screen for a known month.
3. Trend display appears only at ≥ 5 efforts; the caveat flag renders
   for short segments.
4. Every excluded (virtual) effort is flagged in core, absent from the
   mart, and counted in the view's sample-count caption.

**Estimated effort:** 1–2 weekends

## Phase C3 — Wind Direction and Headwind Context (Release 2.1)

**Objective:** Explain slow days on a fixed segment with a per-effort
headwind component (D29, D30).

### Tasks

* [ ] Schema: idempotent `wind_direction_deg` column addition to
      `raw_weather.hourly` in `sql/`, applied by `make bootstrap`.
* [ ] Weather client: request `wind_direction_10m` alongside the
      existing hourly variables; extend the cache-completeness check to
      the new column so pre-migration rows are not frozen as complete.
* [ ] One-time `make reconcile-weather` backfill; resumable across
      runs within `WEATHER_REQUEST_BUDGET`, revisions absorbed by the
      existing `IS DISTINCT FROM` upsert.
* [ ] Staging: `stg_weather__hourly` exposes `wind_direction_deg`
      (0 = north is a value; missing stays NULL).
* [ ] Intermediate: segment bearing (great-circle, start → end
      coordinates from `stg_strava__segments`), sinuosity and the
      `winding_segment` flag (`winding_sinuosity_max`, default 1.3),
      and the effort-hour wind match at the parent ride's start cell
      (60-minute rule).
* [ ] Mart: extend `mart_segment_trend` with `headwind_mph`
      (positive = headwind, the pinned D30 sign), `crosswind_mph`, and
      the winding flag. No allow-list change.
* [ ] App: **Cycling segments** view gains headwind context on the
      trend (per-effort annotation or color), with the winding and
      spatial caveats displayed.

### Acceptance criteria

1. Sign fixtures pass: north travel + wind from north = full positive
   headwind; from south = negative; from east ≈ zero headwind, full
   crosswind.
2. After backfill, every cached location-hour has a direction or an
   explicit NULL; 0° survives as north.
3. `winding_segment` flips exactly at the var threshold on synthetic
   fixtures.
4. Existing weather rows keep their keys; values change only through
   the documented reconcile path.
5. Missing direction degrades the view to the existing trend with an
   explanation, never a crash.

**Estimated effort:** 1–2 weekends

---

## Block 2 — §3 replacements for docs/PROJECT_PLAN.md

Replace the first non-goal bullet with:

> * **Plain replication of standard Strava screens.** Data or views
>   that exist in Strava may enter scope when the project materially
>   improves their interpretability, accessibility, or analytical
>   context — trend statistics, normalization, weather or HR context,
>   or custom thresholds Strava does not offer. The admitting addendum
>   must name the improvement.

Append to the Deferred list:

> * Stream-derived rolling speed and stop-loss metrics (ride branch of
>   the D15 stream fetch gate, idle-speed threshold, pedaling-time
>   share)
> * Polyline-based segment bearing for winding segments
> * Segment efforts for runs
> * Ride cardiac drift (coasting breaks the D16 halves comparison)
> * Speed-at-HR-band on segments (the D22 analog)

Append to the §2 preamble:

> Decisions bind the codebase between revisions; any decision may be
> revised at any time by a recorded addendum — the record, not
> permanence, is the point.

---

## Block 3 — Revisions summary for docs/PROJECT_PLAN.md

# Revision v2.0 — 2026-08-18 — Cycling domain admission (purpose-level revision)

Recorded in `docs/decisions/v2.0-cycling-domain.md`.
Summary: the project becomes an endurance-analytics pipeline with two
peer domains; the running thesis, D1–D7, D9–D18, D20–D22, and all
running output are untouched (byte-identical, pinned by verification —
D15 included: no ride streams are fetched). Cycling primary question:
on fixed segments, is effort time at comparable heart rate improving?
New decisions D23–D30: ride grain (e-bike excluded, `VirtualRide`
indoor-flagged), segment-effort ingestion via per-ride detail fetch
with streams-style status rows, data-validity-only ride rules, cadence
as a first-class field at ride and effort grain, an explicit power
exclusion (estimated watts stay raw-JSONB-only), segment trend
definition (5-effort rolling median, ≥ 5-effort sufficiency, < 120 s
noise flag, virtual efforts held out of marts), wind-direction
ingestion (`wind_direction_deg` on `raw_weather.hourly`, FROM
convention, 0° = north is a value, completeness check extended,
one-time reconcile backfill), and the headwind component
(straight-line segment bearing, `winding_segment` flag at sinuosity
1.3, effort-hour wind match at the ride's start cell, positive =
headwind pinned D17-style, crosswind secondary). D8 gains the wind
variable; D19's cap becomes five views (three running unchanged +
Cycling segments + Cycling training), allow-list mechanics unchanged
with three named red-first additions — C3 extends `mart_segment_trend`
without allow-list growth. The replication non-goal is reworded to
admit Strava-resident data when the addendum names a material
improvement; the §2 preamble states decisions are always revisable by
recorded addendum, never silently skippable. Phases C1–C3 added
(C1+C2 = Release 2.0, C3 = Release 2.1); stream-derived rolling
speed and stop-loss, polyline bearings, run segment efforts, ride
drift, and the segment HR-band analog join the Deferred list.

---

## Block 4 — CLAUDE.md scope constraints

## Scope constraints — Cycling domain (v2.0)
- Running output is byte-identical: no running model, mart, view, or
  test changes in any C-phase. D15 is untouched — no ride streams.
- No power fields modeled while `device_watts` is false — estimated
  watts/kilojoules live in raw JSONB only (D27).
- Ride grain excludes `EBikeRide`/`EMountainBikeRide`; `VirtualRide`
  is indoor-flagged and its segment efforts never reach marts (D23,
  D28).
- Segment views must name their improvement over the Strava screen
  (reworded non-goal); plain replication stays out.
- Detail fetches keep the batch cap and the exit-3 rate-limit
  contract; status rows are the resumability mechanism.
- Wind direction uses the meteorological FROM convention; 0° = north
  is a value, missing is NULL, never zero. Headwind sign is pinned:
  positive = headwind (D30). Winding and short-segment flags are
  displayed, never filters.
- App cap is now 5; allow-list additions are exactly the three named
  marts, each proven red first; C3 adds none (amended D19).
