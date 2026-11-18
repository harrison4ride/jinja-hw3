#!/usr/bin/env python3
"""Trace how Jinja decides where the first value of a name comes from.

For each template the script prints five things:

1. the shape of the ``If`` node the parser built;
2. every call to ``Symbols.branch_update``: the ``stores`` and the load
   instruction of the traced name in each table it receives, the merged
   value, and the value after the call;
3. the result of ``meta.find_undeclared_variables``;
4. the lines of generated Python that initialise the name;
5. the names the rendered template looked up in the context, and the output.

Run with the interpreter of the Jinja checkout under test. Set PYTHONPATH to
the ``src`` directory of another checkout to trace another version.
"""

import jinja2
from jinja2 import Environment
from jinja2 import idtracking
from jinja2 import meta
from jinja2 import nodes
from jinja2.runtime import Context

# (label, traced name, template source, render arguments, expected output)
CASES = [
    (
        "A. issue 2069: if/elif/else all set, then read",
        "output",
        "{% if control == 'something' %}{% set output = 1 %}"
        "{% elif control == 'something else' %}{% set output = 2 %}"
        "{% else %}{% set output = 3 %}{% endif %}[{{ output }}]",
        {"control": "something", "output": "from-context"},
        "[1]",
    ),
    (
        "B. if/else both set, then read",
        "x",
        "{% if c %}{% set x = 1 %}{% else %}{% set x = 2 %}{% endif %}[{{ x }}]",
        {"c": True, "x": "from-context"},
        "[1]",
    ),
    (
        "C. issue 1253: the if branch reads the name before it sets it",
        "a",
        "{% if True %}{{ a.b }}{% set a = 1 %}{% elif False %}{% set a = 2 %}"
        "{% else %}{% set a = 3 %}{% endif %}{{ a }}",
        {"a": {"b": 0}},
        "01",
    ),
    (
        "D. two elifs, the second one does not set",
        "x",
        "{% if a %}{% set x = 1 %}{% elif b %}{% set x = 2 %}{% elif c %}no"
        "{% else %}{% set x = 4 %}{% endif %}[{{ x }}]",
        {"a": False, "b": False, "c": True, "x": "from-context"},
        "no[from-context]",
    ),
    (
        "E. if without else",
        "x",
        "{% if c %}{% set x = 1 %}{% endif %}[{{ x }}]",
        {"c": False, "x": "from-context"},
        "[from-context]",
    ),
    (
        "F. no if statement at all",
        "x",
        "{% set x = 1 %}[{{ x }}]",
        {"x": "from-context"},
        "[1]",
    ),
]


class LoggingContext(Context):
    """Record every name the template resolves from the context."""

    looked_up: list = []

    def resolve_or_missing(self, key):
        LoggingContext.looked_up.append(key)
        return super().resolve_or_missing(key)


def describe_if(node: nodes.If, indent: str = "    ") -> None:
    print(
        f"{indent}If(body={len(node.body)} nodes, "
        f"elif_={[type(n).__name__ for n in node.elif_]}, "
        f"else_={len(node.else_)} nodes)"
    )
    for child in node.elif_:
        describe_if(child, indent + "    ")


def trace(label: str, name: str, source: str, variables: dict, expected: str) -> None:
    print("=" * 78)
    print(label)
    print(f"    {source}")
    env = Environment()
    env.context_class = LoggingContext
    ast = env.parse(source)

    print("  1. AST")
    for node in ast.find_all(nodes.If):
        describe_if(node)
        break
    else:
        print("    no If node")

    print(f"  2. branch_update calls (load instruction of {name!r})")
    original = idtracking.Symbols.branch_update
    depth = [0]

    def traced(self, branch_symbols):
        ref = f"l_{self.level}_{name}"
        merged = dict(self.loads)
        pad = "    " + "  " * depth[0]
        print(f"{pad}call at depth {depth[0]}, {len(branch_symbols)} tables")
        # 3.1.x passes three tables (body, all elifs, else); the fix, which
        # adds Symbols.unused_loads, passes one per branch
        if hasattr(self, "unused_loads"):
            elifs = [f"elif {n}" for n in range(1, len(branch_symbols) - 1)]
            names = ["body", *elifs, "else"]
        elif len(branch_symbols) == 3:
            names = ["body", "elifs", "else"]
        else:
            names = [f"table {n}" for n in range(1, len(branch_symbols) + 1)]
        for table_name, table in zip(names, branch_symbols):
            merged.update(table.loads)
            print(
                f"{pad}  {table_name:6} stores={sorted(table.stores)!s:8}"
                f" load={table.loads.get(ref)}"
            )
        print(f"{pad}  merged, last table wins: {merged.get(ref)}")
        original(self, branch_symbols)
        unused = ref in getattr(self, "unused_loads", ())
        print(
            f"{pad}  after branch_update:     {self.loads.get(ref)}  unused: {unused}"
        )

    def traced_visit_if(self, node, **kwargs):
        depth[0] += 1
        try:
            return original_visit_if(self, node, **kwargs)
        finally:
            depth[0] -= 1

    original_visit_if = idtracking.FrameSymbolVisitor.visit_If
    idtracking.Symbols.branch_update = traced
    idtracking.FrameSymbolVisitor.visit_If = traced_visit_if
    try:
        result = meta.find_undeclared_variables(ast)
    finally:
        idtracking.Symbols.branch_update = original
        idtracking.FrameSymbolVisitor.visit_If = original_visit_if
    if not any(True for _ in ast.find_all(nodes.If)):
        print("    none")

    print(f"  3. find_undeclared_variables -> {sorted(result)}")

    print("  4. generated code that initialises the name")
    code = env.compile(source, raw=True)
    for line in code.splitlines():
        text = line.strip()
        if text.startswith(f"l_0_{name} = resolve") or (
            text.endswith("= missing") and f"l_0_{name}" in text
        ):
            print(f"    {text}")
            break

    LoggingContext.looked_up = []
    try:
        output = env.from_string(source).render(**variables)
    except Exception as error:  # the trace has to continue after a failing render
        output = f"{type(error).__name__}: {error}"
    verdict = "ok" if output == expected else f"WRONG, expected {expected!r}"
    print(f"  5. render({variables})")
    print(f"    context lookups: {LoggingContext.looked_up}")
    print(f"    output: {output!r}  {verdict}")


def main() -> None:
    print(f"jinja2 {jinja2.__version__} from {jinja2.__file__}")
    for case in CASES:
        trace(*case)


if __name__ == "__main__":
    main()
