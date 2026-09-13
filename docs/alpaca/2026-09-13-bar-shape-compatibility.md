# Alpaca retained-bar compatibility correction

Source correction: `0882d62ea6ba4ea18113cb5c535a4b8e9895438f`.

## Finding and scope

The pre-correction `4fa91d3` observation builder required a single-symbol URL
but selected `bars[symbol][index]`, the multi-symbol response layout. Neither
real endpoint/response pairing could pass. Existing positive fixtures combined
the two incompatible shapes and therefore did not expose the defect.

Alpaca's [single-symbol bars reference](https://docs.alpaca.markets/us/reference/stockbarsingle-1),
expanded in the browser on 2026-09-13, specifies a `bars` array plus a response
`symbol`. The authorized retained multi-symbol capture independently supplies
the symbol-keyed map from `/v2/stocks/bars?symbols=...`.

The correction binds the exact endpoint, requested symbol, response shape and
caller-selected JSON path together. Single-symbol sources require matching
response identity and `("bars", index)`; multi-symbol sources require one
unambiguous symbols query containing the security and `("bars", symbol, index)`.
Source bytes are not rewritten or normalized into a different response.

Existing numeric, calendar, availability and custody behavior is unchanged.
Earlier fixtures now use the multi-symbol URL appropriate to their existing
payload and selectors. Added cases reject crossed shapes, missing/mismatched
identity, ambiguous request symbols, foreign selectors, route suffixes and
invalid indices. All values in these tests are explicitly synthetic.

## Verification

Working directory: isolated `tradingagents-alpaca-bar-shapes-20260913`, based on
`4fa91d3e2b7fe0be29952b141ebba7aa2ed3090a`. Canonical Python 3.13.14 environment
reused, feature root explicitly in `PYTHONPATH`, `TA_LIVE_SUBMIT=0`; shared
pytest fixtures block external network and substitute placeholder credentials.

- RED: `python -m pytest -q tests/test_point_in_time_official_observations.py -k documented_endpoint_response_pair`:
  both single/multi regressions failed on original source, 40 deselected, 0.18s.
- GREEN: the complete affected observation module passed **57 tests in 0.44s**.
- Scoped Ruff and `git diff --check` passed. Full two-file source/test diff
  reviewed solo; no additional actionable finding within this correction.
- Read-only retained-byte diagnostic at `2026-09-13T20:41:16.932276+00:00`
  passed on both unmodified captures: 15 symbols and 2,040 bars per response,
  raw and all-adjusted SIP. Every selected bar was the original parsed object;
  all seven numeric fields passed the production numeric validator.
  Socket construction was disabled. No identity was fabricated and no
  observation, admission or qualifying result was created.

The retained body SHA-256 values are
`587b698d8e8306e793cd61bcdaccc49c5397112dac0d79252ea13961deb804ad`
and `769f256d9045fb7e93de1d73a9c92a9ea2eae77e7e06cf2c50b8807b82bd356f`.
The checked parser SHA-256 is
`8c1ff72e9cf16d789fd60fa11e8e49b454e1c0a19c334daa174a32559ed40c28`.

Local diagnostic helper and RED/GREEN XML receipts remain in the canonical
`.superpowers/sdd/2026-08-30-tradingagents-evidence-first-working-state-completion/`
directory (`check_alpaca_retained_bar_shapes_20260913.py` and
`alpaca-bar-shapes-{red,green}-20260913.xml`). Private raw downloads stay ignored
under `results/alpaca_readonly_capture/20260913T200134226135Z/`; standard raw
custody remains in `results/pit_raw_capture/20260913T201816173345Z/`.

## Acceptance boundary

This is a bounded source correction, not Phase 4 or economic readiness
acceptance. The original Phase 4 verifier remains on unchanged `4fa91d3` in
the economic worktree; it was not stopped, edited or duplicated for this fix.
Its eventual receipt covers that candidate, not this follow-up. Integrate the
follow-up only through the existing plan's review/verification checkpoint.
The final combined candidate still needs its prescribed broader gate.

The collected bytes retain their actual September 13 capture times. They do
not prove earlier availability, a registered cohort, security-master effective
dates, SEC custody or historical qualification. No broker/model operation,
schedule change, holdout release or order is authorized by this correction.

Preservation checkpoint `2026-09-13T20:42:55.832122+00:00` passed all four
frozen owner hashes, all ten PAUSED automation hashes, exact LangGraph
HEAD/status/sixteen file hashes and clean canonical/economic worktrees.
