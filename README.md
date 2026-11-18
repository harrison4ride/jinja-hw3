# Jinja 3.1.6 with a Fix for Issue 2069

This repository is [Jinja](https://github.com/pallets/jinja) at tag 3.1.6 plus a fix for
[issue 2069](https://github.com/pallets/jinja/issues/2069): `meta.find_undeclared_variables()`
reports a variable as undeclared even when every branch of an `if`/`elif`/`else` block sets it
before it is used. It is coursework for Homework 3, "Bug Fixing with Coding Agents"; the fix was
developed with Claude Code. The original Jinja README follows [below](#jinja).

## What Changed

The unmodified 3.1.6 release commit (`1520688`) is in the history. Every change since then is in
these commits:

| Tag | Commit | Content | Test suite on that commit |
|---|---|---|---|
| `3.1.6` | `1520688` | Jinja 3.1.6, unmodified | 909 passed |
| `hw3-repro` | `75ba0a2` | 2 tests that reproduce the issue | 2 failed, 909 passed |
| | `437058f` | 38 tests for related scenarios | 13 failed, 936 passed |
| `hw3-tests` | `2b5f583` | tests revised after three code reviews (2 removed, 12 added) | 17 failed, 942 passed |
| | `abaf1e0` | first version of the fix: `src/jinja2/idtracking.py`, `src/jinja2/meta.py`, `CHANGES.rst` | 959 passed |
| | `1e84598` | 11 tests for names that an include, import or block receives before the `if` | 6 failed, 964 passed |
| | `8107a1d` | second version of the fix: `src/jinja2/idtracking.py` and the changelog entry | 970 passed |
| | `746888a` to `144992e` | validation tools in [`hw3/`](hw3/) and this README | 970 passed |
| | `4c3aa3f` | 2 tests for a macro that reads a variable of an overlay scope | 2 failed, 970 passed |
| `hw3-fix` | `00f0603` | the fix, completed: `src/jinja2/idtracking.py` | 972 passed |
| | later commits | this README | 972 passed |

`src/` stays identical to 3.1.6 up to `hw3-tests`, so those test commits run against the original
code. `1e84598` runs its 11 new tests against the first version of the fix, which fails six of
them, and `4c3aa3f` runs its 2 against the second version, which fails both. To read the changes:

```sh
git diff 3.1.6 hw3-fix -- src/ CHANGES.rst    # the fix
git diff 3.1.6 hw3-fix -- tests/              # all new tests
```

## Setup

Requirements: git, Python 3.8 or newer, and a POSIX shell on macOS, Linux or WSL. With a native
Windows Python, use `.venv/Scripts/` in place of `.venv/bin/`. The results below were produced with
Python 3.11.15 and checked with Python 3.8.20 and 3.9.6 on macOS.

```sh
git clone https://github.com/harrison4ride/jinja-hw3.git
cd jinja-hw3
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements/tests.txt -e .
```

The editable install (`-e .`) needs pip 21.3 or newer, so the first pip command upgrades pip; macOS's
`/usr/bin/python3` 3.9.6, for example, comes with pip 21.2.4. The editable install makes the virtual
environment use the checked-out `src/`, so `git checkout` switches the Jinja code that the tests run
against.

## Reproduce the Original Failure

The next steps check out older commits whose `README.md` does not have this section; keep this page
open, or read it with `git show main:README.md`.

Check out the reproduction tests on the unmodified source and run the meta tests:

```sh
git checkout hw3-repro
.venv/bin/python -m pytest tests/test_api.py::TestMeta -v
```

Expected: `2 failed, 3 passed`. The output includes lines like these (pytest pads the separator
lines to the terminal width); the issue's template reports `output` as undeclared:

```text
_________ TestMeta.test_find_undeclared_variables_set_in_all_branches __________
E       AssertionError: assert {'control', 'output'} == {'control'}
tests/test_api.py:196: AssertionError
__________ TestMeta.test_find_undeclared_variables_set_in_if_and_else __________
E       AssertionError: assert {'bar', 'foo'} == {'bar'}
tests/test_api.py:206: AssertionError
```

To run the 50 tests written before the fix against the unmodified source:

```sh
git checkout hw3-tests
.venv/bin/python -m pytest -q    # 17 failed, 942 passed
```

Thirteen of the failures are wrong results of `find_undeclared_variables`; the four in
`tests/test_idtracking.py` fail because 3.1.6 has no `Symbols.unused_loads`. To run all 63 new tests
against 3.1.6, use the reference worktree that [`hw3/README.md`](hw3/README.md#reference-build)
describes, from `main`: `PYTHONPATH=../jinja-3.1.6/src .venv/bin/python -m pytest -q` gives
`23 failed, 949 passed`.

The example from the issue gives the same result outside the tests:

```sh
.venv/bin/python - <<'EOF'
from jinja2 import Environment, meta
source = (
    "{% if control == 'something' %}{% set output = 1 %}"
    "{% elif control == 'something else' %}{% set output = 2 %}"
    "{% else %}{% set output = 3 %}{% endif %}{{ output }}"
)
print(sorted(meta.find_undeclared_variables(Environment().parse(source))))
EOF
```

On `3.1.6`, `hw3-repro` and `hw3-tests` it prints `['control', 'output']`; on `main` it prints
`['control']`.

## Run the Tests With the Fix

```sh
git checkout main
.venv/bin/python -m pytest tests/test_api.py::TestMeta -v    # 45 passed
.venv/bin/python -m pytest -q                                # 972 passed
.venv/bin/python -m pytest tests/test_api.py::TestMeta tests/test_idtracking.py tests/test_regression.py -q    # 125 passed
```

The two reproduction tests that failed on `hw3-repro` now pass; the output includes lines like:

```text
tests/test_api.py::TestMeta::test_find_undeclared_variables_set_in_all_branches PASSED
tests/test_api.py::TestMeta::test_find_undeclared_variables_set_in_if_and_else PASSED
```

The 63 new tests:

| File | New tests | What they check |
|---|---|---|
| `tests/test_api.py::TestMeta` | 42 | `find_undeclared_variables` with names set in every branch (the issue's template, `if`/`else`, more `elif`s, nested `if`s, tuple and block assignments, macros, loops), in some branches only, read before the set (in a test, in the value, in a loop or macro that runs first), passed to an include, import or scoped block before or after the `if`, and read by a macro called in an overlay scope |
| `tests/test_idtracking.py` | 5 | the symbol analysis: one table per `elif`, `Symbols.unused_loads`, nested frames and macros that load the name, and overlay scopes |
| `tests/test_regression.py` | 16 | rendering stays as in 3.1.6: an `elif` that does not set the name, nested frames that read it first, and macros kept from an earlier loop iteration or a sibling frame |

The repository's own type and style checks also pass:

```sh
.venv/bin/python -m pip install -r requirements/typing.txt ruff==0.8.4
.venv/bin/python -m mypy                       # Success: no issues found in 25 source files
.venv/bin/ruff check --no-fix src tests hw3    # All checks passed!
.venv/bin/ruff format --check src tests hw3    # 56 files already formatted
```

## How the Fix Works

When an `if`/`elif`/`else` block stores a name that its frame has not stored before,
`Symbols.branch_update` in `src/jinja2/idtracking.py` gives the name the load instruction
`resolve` (`alias` in a nested frame whose parent has the name). `resolve` looks the name up in the
template context when the frame starts, and `meta.find_undeclared_variables` reports every
`resolve` of a name that is not a global. So it reports `output`, although every branch sets it
before it is read. Version 3.1.5 made every branch-stored name a lookup to fix issue 1253, where a
branch reads the name before setting it. The lookup matters in more cases: a macro kept from
earlier, a nested frame that shares the variable, or an included template can see the looked-up
value before the branches set the name.

The fix leaves the generated code unchanged. The symbol analysis now treats each `elif` as a branch
of its own and records a load in `Symbols.unused_loads` when every branch stores the name before
loading it and no code that may run earlier could read the looked-up value. Three kinds of code
could: a nested frame that runs before the store and loads the name (a loop, `with`, filter or set
block, a scoped block or an overlay scope); a macro or call block of the same function that loads it
(macros inside unscoped blocks are skipped, since blocks cannot see the frame's variables); and an
include or import with context, or a derived context reference, before the store, which hands all of
the frame's variables to code that is not analysed here. A nested frame or macro that contains such
an include counts as loading every name. An overlay scope, a node that only extensions create, is
analysed without the frame around it, so the analysis cannot see the macros that may run in it and
counts every name as loaded by one. `meta` skips the recorded loads. For 25,244 template and mode
pairs, the generated Python is identical to 3.1.6; see [`hw3/README.md`](hw3/README.md).

Known limitations. Some names are still reported although no path uses their lookup, as in 3.1.6:
a name set in only some branches and never read afterwards; a name that a nested frame before the
`if` reads, even one that sets it first; a name that any macro or call block of the function reads,
even one the macro only uses locally; every name of a frame in which an include or import with
context runs before the `if`, or whose function has a macro that contains one, whatever the included
template reads; and every name set in all branches inside an overlay scope. Names that an included
template reads from the context by itself are not reported, as before: `meta` does not look into
included templates.

## Validation Beyond the Test Suite

[`hw3/`](hw3/) holds the scripts used to validate the fix: probes, traces, include and kept-macro
cases, a differential test over 12,000 distinct random templates with a rendering oracle, and the
generated-code comparison. Its [README](hw3/README.md) lists the commands and expected results.

## GitHub Actions

The workflows in `.github/workflows/` are Jinja's own, and they fail in this repository for reasons
unrelated to the fix. `Publish` runs on every tag push and fails at the upload to PyPI, which has no
trusted publisher for this repository, so nothing reaches PyPI. `Tests` fails in the same jobs on
the unmodified 3.1.6 commit. Two causes show in the job annotations and in a local run: the Ubuntu
26.04 runner has no Python 3.7, 3.8 or 3.9, and tox 4.67, which `pip install tox` now installs,
rejects environment names such as `py3.11` ("did you mean py311?"). The commands in this README run
pytest directly.

---

# Jinja

Jinja is a fast, expressive, extensible templating engine. Special
placeholders in the template allow writing code similar to Python
syntax. Then the template is passed data to render the final document.

It includes:

-   Template inheritance and inclusion.
-   Define and import macros within templates.
-   HTML templates can use autoescaping to prevent XSS from untrusted
    user input.
-   A sandboxed environment can safely render untrusted templates.
-   AsyncIO support for generating templates and calling async
    functions.
-   I18N support with Babel.
-   Templates are compiled to optimized Python code just-in-time and
    cached, or can be compiled ahead-of-time.
-   Exceptions point to the correct line in templates to make debugging
    easier.
-   Extensible filters, tests, functions, and even syntax.

Jinja's philosophy is that while application logic belongs in Python if
possible, it shouldn't make the template designer's job difficult by
restricting functionality too much.


## In A Nutshell

```jinja
{% extends "base.html" %}
{% block title %}Members{% endblock %}
{% block content %}
  <ul>
  {% for user in users %}
    <li><a href="{{ user.url }}">{{ user.username }}</a></li>
  {% endfor %}
  </ul>
{% endblock %}
```

## Donate

The Pallets organization develops and supports Jinja and other popular
packages. In order to grow the community of contributors and users, and
allow the maintainers to devote more time to the projects, [please
donate today][].

[please donate today]: https://palletsprojects.com/donate

## Contributing

See our [detailed contributing documentation][contrib] for many ways to
contribute, including reporting issues, requesting features, asking or answering
questions, and making PRs.

[contrib]: https://palletsprojects.com/contributing/
