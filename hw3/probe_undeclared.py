#!/usr/bin/env python3
"""Probe meta.find_undeclared_variables() on a set of small templates.

For each template the script prints the value the function returns and the
value I expect. The expectation follows the function's documented contract:
a name belongs in the result when some execution path reads it before the
template has assigned it, so the value has to come from the context.

Run with the interpreter of the Jinja checkout under test:
  .venv/bin/python hw3/probe_undeclared.py
"""

import jinja2
from jinja2 import Environment
from jinja2 import meta

ISSUE_EXAMPLE = """\
{% if control == 'something' %}
    {% set output = 1 %}
{% elif control == 'something else' %}
    {% set output = 2 %}
{% else %}
    {% set output = 3 %}
{% endif %}
{{ output }}
"""

# (label, template source, expected result, reason for the expectation)
PROBES = [
    (
        "issue example: if/elif/else all set, then read",
        ISSUE_EXAMPLE,
        {"control"},
        "every path assigns output before the read",
    ),
    (
        "if/else both set, then read",
        "{% if c %}{% set x = 1 %}{% else %}{% set x = 2 %}{% endif %}{{ x }}",
        {"c"},
        "every path assigns x before the read",
    ),
    (
        "if only (no else), then read",
        "{% if c %}{% set x = 1 %}{% endif %}{{ x }}",
        {"c", "x"},
        "when c is false, x comes from the context",
    ),
    (
        "if/elif (no else) both set, then read",
        "{% if c %}{% set x = 1 %}{% elif d %}{% set x = 2 %}{% endif %}{{ x }}",
        {"c", "d", "x"},
        "when c and d are false, x comes from the context",
    ),
    (
        "if/else, only the if branch sets, then read",
        "{% if c %}{% set x = 1 %}{% else %}no{% endif %}{{ x }}",
        {"c", "x"},
        "the else path leaves x unassigned",
    ),
    (
        "if/elif/else, the elif branch does not set, then read",
        "{% if c %}{% set x = 1 %}{% elif d %}no{% else %}{% set x = 3 %}{% endif %}"
        "{{ x }}",
        {"c", "d", "x"},
        "the elif path leaves x unassigned",
    ),
    (
        "two elifs, all four branches set, then read",
        "{% if a %}{% set x = 1 %}{% elif b %}{% set x = 2 %}"
        "{% elif c %}{% set x = 3 %}"
        "{% else %}{% set x = 4 %}{% endif %}{{ x }}",
        {"a", "b", "c"},
        "every path assigns x before the read",
    ),
    (
        "two elifs, the second elif does not set, then read",
        "{% if a %}{% set x = 1 %}{% elif b %}{% set x = 2 %}{% elif c %}no"
        "{% else %}{% set x = 4 %}{% endif %}{{ x }}",
        {"a", "b", "c", "x"},
        "the second elif path leaves x unassigned",
    ),
    (
        "nested if/else inside the if branch, all leaves set, then read",
        "{% if a %}{% if b %}{% set x = 1 %}{% else %}{% set x = 2 %}{% endif %}"
        "{% else %}{% set x = 3 %}{% endif %}{{ x }}",
        {"a", "b"},
        "every path assigns x before the read",
    ),
    (
        "nested if without else inside the if branch, then read",
        "{% if a %}{% if b %}{% set x = 1 %}{% endif %}{% else %}{% set x = 3 %}"
        "{% endif %}{{ x }}",
        {"a", "b", "x"},
        "a true and b false leaves x unassigned",
    ),
    (
        "read before the if/else",
        "{{ x }}{% if c %}{% set x = 1 %}{% else %}{% set x = 2 %}{% endif %}",
        {"c", "x"},
        "the first read happens before any assignment",
    ),
    (
        "set before the if/else, then read",
        "{% set x = 0 %}{% if c %}{% set x = 1 %}{% else %}{% set x = 2 %}{% endif %}"
        "{{ x }}",
        {"c"},
        "x is assigned before the conditional",
    ),
]


def main() -> None:
    env = Environment()
    print(f"jinja2 {jinja2.__version__} from {jinja2.__file__}")
    wrong = 0
    for label, source, expected, reason in PROBES:
        got = meta.find_undeclared_variables(env.parse(source))
        verdict = "ok   " if got == expected else "WRONG"
        wrong += got != expected
        print(f"{verdict} {label}")
        print(f"        got      {sorted(got)}")
        print(f"        expected {sorted(expected)}   ({reason})")
    print(f"{wrong} of {len(PROBES)} probes differ from the expectation")


if __name__ == "__main__":
    main()
