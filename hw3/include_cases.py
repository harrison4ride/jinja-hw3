#!/usr/bin/env python3
"""Templates that give a name to another template before the if sets it.

An include or import with context, and a scoped block, receive the
variables of the frame they run in. If one runs before every branch of an
if block sets a name, it sees the value the template looked up in the
context, so find_undeclared_variables has to report the name. For each
case the script prints whether the name is reported and whether the
output depends on it.

Usage, with the interpreter of the build under test:
  .venv/bin/python hw3/include_cases.py
"""

import jinja2
from jinja2 import DictLoader
from jinja2 import Environment
from jinja2 import meta

SET_X = "{% if a %}{% set x = 1 %}{% else %}{% set x = 2 %}{% endif %}"
CASES = [
    ("C1 include before the if", "{% include 'inc' %}" + SET_X),
    (
        "C2 include in a loop before the if",
        "{% for i in [0] %}{% include 'inc' %}{% endfor %}" + SET_X,
    ),
    (
        "C3 import with context before the if",
        "{% import 'mod' as m with context %}{{ m.v }}" + SET_X,
    ),
    (
        "C4 from-import with context before",
        "{% from 'mod' import v with context %}{{ v }}" + SET_X,
    ),
    (
        "C5 scoped block before the if",
        "{% block b scoped %}{% include 'inc' %}{% endblock %}" + SET_X,
    ),
    (
        "C6 include in a macro called first",
        "{% macro m() %}{% include 'inc' %}{% endmacro %}{{ m() }}" + SET_X,
    ),
    (
        "C7 include in a branch before set",
        "{% if a %}{% include 'inc' %}{% set x = 1 %}"
        "{% else %}{% set x = 2 %}{% endif %}",
    ),
    (
        "C8 include without context before",
        "{% include 'inc' without context %}" + SET_X,
    ),
    ("C9 include after the if", SET_X + "{% include 'inc' %}"),
]


def main() -> None:
    env = Environment(loader=DictLoader({"inc": "[{{ x }}]", "mod": "{% set v = x %}"}))
    print(f"jinja2 {jinja2.__version__} from {jinja2.__file__}")
    for label, source in CASES:
        reported = "x" in meta.find_undeclared_variables(env.parse(source))
        with_x = env.from_string(source).render(a=True, x="ctx")
        without_x = env.from_string(source).render(a=True)
        print(
            f"{label:38} reports x: {str(reported):5}"
            f"  needed: {str(with_x != without_x):5}"
            f"  output {with_x!r} / without x {without_x!r}"
        )


if __name__ == "__main__":
    main()
