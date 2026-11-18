# Validation Tools for Issue 2069

These scripts validated the fix beyond Jinja's test suite. They are not part of Jinja and do not
run in its test suite. Each script uses the `jinja2` package on the import path, so the same script
measures any build: the fixed checkout, or tag 3.1.6 through `PYTHONPATH`. Every script prints the
path of the `jinja2` package it loaded, because both builds report version 3.1.6.

All commands run from the repository root, in a POSIX shell, with the virtual environment from the
main [README](../README.md#setup).

## Reference Build

The comparisons need unmodified Jinja 3.1.6 next to the fixed checkout. A git worktree provides
it without a second clone:

```sh
git worktree add ../jinja-3.1.6 3.1.6
```

Run a script against 3.1.6 by putting its sources first on the import path:

```sh
PYTHONPATH=../jinja-3.1.6/src .venv/bin/python hw3/probe_undeclared.py
```

The first line of the output names the loaded package, here `.../jinja-3.1.6/src/jinja2/__init__.py`.
Do not add `-I` to these commands: isolated mode ignores `PYTHONPATH`, and the script would measure
the fixed checkout instead.

## Scripts

| Script | What it checks | Result on 3.1.6 | Result with the fix |
|---|---|---|---|
| `probe_undeclared.py` | 12 small templates: names set in all, some, or nested branches, read before or after | 4 of 12 differ from the expectation | 0 of 12 |
| `trace_branch_update.py` | For six templates: every `Symbols.branch_update` call with each branch table, the generated line that initialises the name, and the names a render looks up | the load becomes `resolve` | the load stays `resolve` and is marked `unused` where no path needs it; same initialisation line |
| `corner_nested_reads.py` | 13 templates: 3 without an `if`, and 10 where a loop, macro, include, block or direct read uses the name before or after an `if` | reference | output identical; `meta` changes for 1 template (A1, a loop after the `if`) |
| `kept_macros.py` | 7 templates where a macro kept in a namespace runs before the `if` sets the name | reference | output identical |
| `include_cases.py` | 9 templates where an include, import or scoped block gets the name before or after the `if` | reports `x` in all 9 | reports `x` in the 7 that need it |
| `differential.py` | 12,000 distinct random templates, rendered under every path and context | reference | see below |
| `same_code.py` | Compiles every template on two builds and compares the generated Python | reference | 0 of 25,244 differ |

Run the five small scripts on the fixed checkout as below; for 3.1.6, put
`PYTHONPATH=../jinja-3.1.6/src` in front of each command.

```sh
.venv/bin/python hw3/probe_undeclared.py
.venv/bin/python hw3/trace_branch_update.py
.venv/bin/python hw3/corner_nested_reads.py
.venv/bin/python hw3/kept_macros.py
.venv/bin/python hw3/include_cases.py
```

## Differential Test

`differential.py dump` generates 12,000 distinct templates from a fixed seed (593). The grammar has
sets, reads, `if`/`elif`/`else`, loops, `with`, set blocks, filter blocks, call blocks, `autoescape`,
macro calls, macros kept in a namespace across loop iterations, includes with and without context,
and imports with context. The script renders each template under every truth assignment of its condition
variables and every subset of `{x, y}` in the context: 1,154,196 renders, plus the marker renders
described next.

The oracle asks whether the template's own lookup of a name is used. The script renders each
template again with a context that answers the template's lookups of one name with a marker: a value
that is false and prints as `#MARK#`. Included and imported templates look names up in their own
contexts, which return the real value. If the marker changes some output, the lookup is used, and
`find_undeclared_variables` must report the name. `compare` takes this from the reference build and
reports, for both builds:

- **misses a used lookup**: a template where a used lookup is not reported. This must be 0.
- **names reported but unused**: names reported although no output uses their lookup.
- **needed only by an included template**: templates in which an included template reads a name
  from the context itself. `meta` has never reported such names; the count is for information.

Each `dump` takes one to two minutes on an Apple M1 Pro (1 min 13 s with Python 3.11, about 2 min
with macOS's Python 3.9.6):

```sh
PYTHONPATH=../jinja-3.1.6/src .venv/bin/python hw3/differential.py dump /tmp/ref.json
.venv/bin/python hw3/differential.py dump /tmp/fix.json
.venv/bin/python hw3/differential.py compare /tmp/ref.json /tmp/fix.json
```

Expected result of `compare`:

| Build | Templates whose output differs | Templates missing a used lookup | Names reported but unused |
|---|---|---|---|
| 3.1.6 (reference) | n/a | 0 | 188 flat + 3,189 nested |
| fix | 0 | 0 | 48 flat + 2,715 nested |

"Flat" templates (404 of them) contain no loop, `with`, macro call, include or other nested frame.
The fix reports fewer names in 606 templates and more names in none.

## Generated Code Comparison

`same_code.py` compiles every template from a dump plus every template string in the test files it
is given, in sync and async mode, and stores a hash of the generated Python. Give both runs the
fixed checkout's `tests`, which include the new tests. Each run takes about a minute and prints
nothing until it finishes:

```sh
PYTHONPATH=../jinja-3.1.6/src .venv/bin/python hw3/same_code.py /tmp/ref.json tests /tmp/code-ref.json
.venv/bin/python hw3/same_code.py /tmp/ref.json tests /tmp/code-fix.json
.venv/bin/python hw3/same_code.py --compare /tmp/code-ref.json /tmp/code-fix.json
```

Expected: `template/mode pairs compiled: 25244` (12,000 random templates and 622 templates from the
test files, in two modes) and `pairs whose generated code differs: 0`. Equal generated code means
equal rendering for every context, so the fix cannot change what these templates render.

## Cleanup

```sh
git worktree remove ../jinja-3.1.6
```
