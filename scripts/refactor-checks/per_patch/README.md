# Per-patch report (check 3)

Shows how far each Larch patch moves the app's results. Each patch is left out in turn
(`larch-patches/build.py --exclude NNNN`), and pure upstream is built too (`--pure-upstream`).
Each variant runs the baseline-match scenarios (`../baseline_match/`) and the team regression
tests. Each capture is then compared with the full patch set's capture.

## Use

```sh
python3.12 scripts/refactor-checks/per_patch/run_variants.py \
    --work <scratch dir> --out <evidence dir> --upstream <local xraylarch clone or URL> \
    [--python python3.12] [--variants 0003 0005+0006+0007 pure] [--baseline <baseline-match capture>] \
    [--reference <existing full capture>] [--keep-captures]

# one pair of captures, by hand
python scripts/refactor-checks/per_patch/summarize.py <reference capture> <variant capture>
```

- One scratch venv (`<work>/venv`) is made like the release env: the release constraints as
  requirements and constraints, then `backend/requirements.txt`. Each variant's wheel replaces
  the previous one, installed under the same constraints. `pip check` must pass.
- `full` runs first and is the reference, unless `--reference` names an existing `full`
  capture. With `--baseline`, the `full` capture is also compared exactly with that capture
  (`compare.py`).
- A variant can leave out several patches (`0005+0006+0007`). This is needed when a later
  patch does not apply without an earlier one. A selection that `build.py` refuses is recorded
  as "does not build", with build.py's reason, and the run goes on.
- The output folder gets, per variant: `<variant>.json` (IDENTITY, regression outcome, per-scenario
  summary), `<variant>.log`, `<variant>-regression.xml`. It also gets `sections.md`, one Markdown
  section per variant.
- Captures (about 430 MB each) and builds are deleted once summarized, unless `--keep-captures`.
- Each variant takes about 2 minutes (build about 40 s, capture about 70 s), `full` about 3.
- At pin `8d6cd41c2`, 0005 and 0006 cannot be left out alone: 0006 needs 0005's
  `feffdat.py` context, and 0007 needs 0006's. The run for the report therefore used
  `--variants 0001 0002 0003 0004 0005 0006 0007 0006+0007 0005+0006+0007 pure`. The effect of
  0006 is `0006+0007` minus `0007`, and the effect of 0005 is `0005+0006+0007` minus `0006+0007`.
- Tests: `backend/.venv/bin/python -m pytest scripts/refactor-checks/per_patch/tests`.

## What the summary measures (`summarize.py`)

Per scenario, steps are paired by position. Every differing value is put in a **field**: the
step's name plus the JSON path inside the step, with list indices written `[*]`. A whole array is
one field.

- `values`: how many numbers differ. Numbers inside text lines (CSV and `.prj` exports) count too,
  when the two lines differ only in their numbers.
- `max_abs`: the largest `|variant - reference|`.
- `max_rel`: the largest `|variant - reference| / |reference|`, value by value (∞ when the
  reference is 0). It is large where an array crosses zero, so read it together with the next one.
- `max_rel_rms`: for numeric arrays, `‖variant - reference‖₂ / ‖reference‖₂` over the whole
  array; the largest over the field's arrays.
- `other`, `example`: differences that are not numbers (text, type, a missing key, a length, an
  HTTP status), and the first one.

A scenario's status is `identical`, `differs`, or `fails`. It fails when:

- a step that succeeded with the full patch set fails in the variant (HTTP ≥ 400);
- a field whose name ends in `error` (e.g. a group's `processing_error`) holds a message in the
  variant where the reference has none. The app reports a Larch failure this way, inside a 200
  response; or
- the variant stops with an error the reference does not have.

`missing` means a scenario is in only one capture.
