#!/usr/bin/env python3
"""Render templates where a macro or caller is kept and called before a
name is set in all branches of an if block.

A loop resets its variables at the start of every iteration, and sibling
frames at one nesting level share Python variable names, so a kept macro
can see a variable before the if block sets it. Jinja 3.1.6 lets it see
the value from the context. The fix for issue 2069 must not change that.

Usage, with the interpreter of the build under test:
  .venv/bin/python hw3/kept_macros.py
"""

import jinja2
from jinja2 import Environment

SET_X = "{% if a %}{% set x = 5 %}{% else %}{% set x = 0 %}{% endif %}"
CALL = "{% if ns.f %}({{ ns.f() }}){% endif %}"
KEEP = "{% macro m() %}{{ x }}{% endmacro %}{% set ns.f = m %}"
KEEP_CALLER = "{% call k() %}{{ x }}{% endcall %}"

CASES = {
    "loop body": "{% for i in [1, 2] %}" + CALL + SET_X + KEEP + "{% endfor %}",
    "loop body, caller": "{% for i in [1, 2] %}"
    + CALL
    + SET_X
    + KEEP_CALLER
    + "{% endfor %}",
    "with block in a loop": "{% for i in [1, 2] %}{% with %}"
    + CALL
    + SET_X
    + KEEP
    + "{% endwith %}{% endfor %}",
    "filter block in a loop": "{% for i in [1, 2] %}{% filter upper %}"
    + CALL
    + SET_X
    + KEEP
    + "{% endfilter %}{% endfor %}",
    "set block in a loop": "{% for i in [1, 2] %}{% set y %}"
    + CALL
    + SET_X
    + KEEP
    + "{% endset %}{{ y }}{% endfor %}",
    "loop else in a loop": "{% for i in [1, 2] %}{% for j in [] %}{% else %}"
    + CALL
    + SET_X
    + KEEP
    + "{% endfor %}{% endfor %}",
    "sibling with blocks": "{% with %}{% set x = 1 %}"
    + KEEP
    + "{% endwith %}{% with %}"
    + CALL
    + SET_X
    + "{% endwith %}",
}

PREFIX = (
    "{% set ns = namespace(f=none) %}"
    "{% macro k() %}{% set ns.f = caller %}{% endmacro %}"
)


def main() -> None:
    env = Environment()
    print(f"jinja2 {jinja2.__version__} from {jinja2.__file__}")
    for label, source in CASES.items():
        output = env.from_string(PREFIX + source).render(a=True, x="ctx")
        print(f"{label:24} {output!r}")


if __name__ == "__main__":
    main()
