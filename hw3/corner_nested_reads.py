#!/usr/bin/env python3
"""Record what happens when a nested scope reads a name before the enclosing
scope assigns it.

A fix that stops the compiler from looking a name up in the context changes
what such a nested scope sees. This script prints, for each template, the
result of meta.find_undeclared_variables and the rendered output, so the
behaviour before and after a patch can be compared line by line.

Every template is rendered with x="ctx" in the context.
"""

import jinja2
from jinja2 import DictLoader
from jinja2 import Environment
from jinja2 import meta

MACRO = "{% macro m() %}[{{ x }}]{% endmacro %}"
ALL = "{% if c %}{% set x = 1 %}{% else %}{% set x = 2 %}{% endif %}"

CASES = [
    # straight-line code: no if statement, shows the rule Jinja already applies
    ("S1 no if: macro call, then set", MACRO + "{{ m() }}{% set x = 1 %}{{ m() }}"),
    (
        "S2 no if: for loop reads, then set",
        "{% for i in [1] %}[{{ x }}]{% endfor %}{% set x = 1 %}[{{ x }}]",
    ),
    ("S3 no if: direct read, then set", "[{{ x }}]{% set x = 1 %}[{{ x }}]"),
    # every branch sets x, and a nested scope reads x before the set
    ("N1 macro call before the if", MACRO + "{{ m() }}" + ALL + "{{ m() }}"),
    (
        "N2 for loop before the if",
        "{% for i in [1] %}[{{ x }}]{% endfor %}" + ALL + "[{{ x }}]",
    ),
    (
        "N3 for loop inside the branch, before set",
        "{% if c %}{% for i in [1] %}[{{ x }}]{% endfor %}{% set x = 1 %}"
        "{% else %}{% set x = 2 %}{% endif %}[{{ x }}]",
    ),
    (
        "N4 include inside the branch, before set",
        "{% if c %}{% include 'inc' %}{% set x = 1 %}{% else %}{% set x = 2 %}"
        "{% endif %}{% include 'inc' %}",
    ),
    (
        "N5 block inside the branch, before set",
        "{% if c %}{% block b %}[{{ x }}]{% endblock %}{% set x = 1 %}"
        "{% else %}{% set x = 2 %}{% endif %}[{{ x }}]",
    ),
    (
        "N6 direct read inside the branch, before set",
        "{% if c %}[{{ x }}]{% set x = 1 %}{% else %}{% set x = 2 %}{% endif %}"
        "[{{ x }}]",
    ),
    # nested scopes that read x after the set: nothing may change here
    ("A1 for loop after the if", ALL + "{% for i in [1] %}[{{ x }}]{% endfor %}"),
    ("A2 macro call after the if", MACRO + ALL + "{{ m() }}"),
    # only one branch sets x: nothing may change here
    (
        "P1 partial: macro call before the if",
        MACRO + "{{ m() }}{% if c %}{% set x = 1 %}{% endif %}{{ m() }}",
    ),
    (
        "P2 partial: for loop before the if",
        "{% for i in [1] %}[{{ x }}]{% endfor %}{% if c %}{% set x = 1 %}{% endif %}"
        "[{{ x }}]",
    ),
]


def main() -> None:
    env = Environment(loader=DictLoader({"inc": "[{{ x }}]"}))
    print(f"jinja2 {jinja2.__version__} from {jinja2.__file__}")
    print("context: c=True, x='ctx'")
    for label, source in CASES:
        reported = "x" in meta.find_undeclared_variables(env.parse(source))
        output = env.from_string(source).render(c=True, x="ctx")
        print(f"{label:46} reports x: {str(reported):5}  output: {output}")


if __name__ == "__main__":
    main()
