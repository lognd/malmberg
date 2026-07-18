# Tickets

Central ledger managed by `frob ticket` -- one section per ticket.

<!-- ticket:T-0001 -->
```yaml
id: T-0001
title: 'frob compliance: zero warnings'
state: done
kind: feature
origin: agent
created: '2026-07-17'
blocked_by: []
parent: null
scope:
- frob.toml,pyproject.toml,docs/index.md,scripts/,src/,tests/
evidence:
- 'ruff check .: All checks passed'
attachments: []
acceptance: []
threat: null
```
## Done report

Adopted frob for malmberg: frob.toml (uv-based test runner, graph excludes
for tests/manual, egg-info, __pycache__), [tool.frob] check_base="main" in
pyproject.toml, .gitignore gained .frob/. `frob graph build` parsed 536
files / 2830 symbols with no crashes (no exclude needed for a builder bug).

Baseline `frob check`: ruff-check 2 errors (E501, F401), ruff-format 1 file,
ty 140 diagnostics, DOC001 3 errors, gates 1187 warnings (COV001 800,
TEST001 278, PERF003 44, PERF004 32, TEST003 23, PERF001 6, TEST006 1),
frob-dup 341 groups, frob-arch 218 warnings/162 suggestions, frob-exports
~470 symbols across 18 packages.

Fixed this mission: ruff-check errors (unused import in scripts/release.py,
long line in scripts/fix_google_takeout_exif.py), ruff-format (same file),
and all 3 DOC001 errors by linking docs/hardware/README.md,
docs/operations/bulk-upload.md, docs/operations/cloud-sync.md from
docs/index.md. `ruff check .` now passes clean.

Remainder (140 ty diagnostics, 1187 gate warnings, 341 dup groups, 380
arch findings, ~470 export gaps) far exceeds the ~150-finding single-mission
budget and is split into repo-local tickets T-0002..T-0007 by category, per
playbook step 5.

<!-- ticket:T-0002 -->
```yaml
id: T-0002
title: 'ty: 140 type diagnostics (unresolved imports for optional extras, invalid-argument-type,
  invalid-type-form)'
state: queued
kind: bug
origin: agent
created: '2026-07-17'
blocked_by: []
parent: null
scope:
- src/,tests/
evidence: []
attachments: []
acceptance: []
threat: null
```

<!-- ticket:T-0003 -->
```yaml
id: T-0003
title: 'gates COV001/TEST001/TEST003/TEST006: missing doc/test bindings (~1100 findings)'
state: queued
kind: feature
origin: agent
created: '2026-07-17'
blocked_by: []
parent: null
scope:
- src/,tests/
evidence: []
attachments: []
acceptance: []
threat: null
```

<!-- ticket:T-0004 -->
```yaml
id: T-0004
title: 'gates PERF001/PERF003/PERF004: perf findings (~82)'
state: queued
kind: feature
origin: agent
created: '2026-07-17'
blocked_by: []
parent: null
scope:
- src/
evidence: []
attachments: []
acceptance: []
threat: null
```

<!-- ticket:T-0005 -->
```yaml
id: T-0005
title: 'frob-exports: ~470 public symbols missing from __init__.py across src/ and
  tests/'
state: queued
kind: feature
origin: agent
created: '2026-07-17'
blocked_by: []
parent: null
scope:
- src/,tests/
evidence: []
attachments: []
acceptance: []
threat: null
```

<!-- ticket:T-0006 -->
```yaml
id: T-0006
title: 'frob-dup: 341 duplicate code groups (326 exact, 15 renamed)'
state: queued
kind: feature
origin: agent
created: '2026-07-17'
blocked_by: []
parent: null
scope:
- src/,tests/
evidence: []
attachments: []
acceptance: []
threat: null
```

<!-- ticket:T-0007 -->
```yaml
id: T-0007
title: 'frob-arch: 218 warnings + 162 suggestions (long-function, god-class, deep-nesting,
  abstraction-opportunity, large-file)'
state: queued
kind: feature
origin: agent
created: '2026-07-17'
blocked_by: []
parent: null
scope:
- src/
evidence: []
attachments: []
acceptance: []
threat: null
```
