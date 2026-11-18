#!/usr/bin/env python3
"""Differential and oracle test for meta.find_undeclared_variables.

The script generates distinct random templates from a small grammar (set,
read, if / elif / else, for loops that run once or twice, with, set blocks,
filter blocks, call blocks, autoescape scopes, macro calls, macros or
callers kept in a namespace and called in a later loop iteration,
includes with and without context, and imports with context) with a fixed
seed. For each template it records, under the Jinja version on the import
path:

* ``reported``: the result of ``meta.find_undeclared_variables``;
* ``outputs``: the rendered output for every truth assignment of the
  condition variables and every subset of {x, y} present in the context;
* ``used``: the names whose lookup by the template is used. While
  rendering, the template's own context lookups of the name return a
  falsy marker that prints as ``#MARK#``; lookups by included or imported
  templates are not marked. If the marker changes some output, the lookup
  is used. This is the oracle: it comes from running the template, so it
  does not depend on anybody's reading of the analysis, and the generator
  makes every read reach the output;
* ``needed``: the names whose presence in the context changes some output.
  Unlike ``used`` it also counts names that an included template reads
  from the context itself, which ``meta`` has never reported.

``compare`` takes ``used`` from the reference dump and checks each dump's
``reported``:

* misses a used lookup: ``used`` is not a subset of ``reported``. This is
  the soundness criterion; it must be 0.
* names reported but unused: ``reported - used``, the imprecision.
* needed only by an included template: templates where ``needed`` has a
  name that ``used`` lacks (information only).

Usage:
  differential.py dump OUT.json [--count N] [--seed S]
  differential.py compare REFERENCE.json CANDIDATE.json

``dump`` uses the jinja2 package on the import path; set PYTHONPATH to the
``src`` directory of the checkout to measure. ``compare`` reports rendering
differences and the two properties for both dumps.
"""

import argparse
import itertools
import json
import random
import re
import sys

VARS = ("x", "y")
MAX_DEPTH = 3
MAX_TESTS = 6  # every test has its own condition variable, so 2**6 paths at most
MACROS = "".join(
    f"{{% macro m_{v}() %}}<{v}:{{{{ {v} }}}}>{{% endmacro %}}" for v in VARS
)
WRAP = "{% macro m_wrap() %}({{ caller() }}){% endmacro %}"
# a namespace that carries a macro or a caller from one loop iteration to the next
KEEP = (
    "{% set ns = namespace(f=none) %}"
    "{% macro m_keep() %}{% set ns.f = caller %}{% endmacro %}"
)
PRESENCE = ("xy", "x", "y", "")  # which of x and y the context contains
# default object reprs contain memory addresses, which change on every render
ADDRESS = re.compile(r" at 0x[0-9a-f]+", re.IGNORECASE)
# templates for includes and imports: each prints or exports one variable
LOADED = {
    **{f"inc_{v}": f"<i{v}:{{{{ {v} }}}}>" for v in VARS},
    **{f"mod_{v}": f"{{% set value = {v} %}}" for v in VARS},
}


class Generator:
    """Build one random template.

    Every read reaches the output: reads print their value, a copy prints
    the copied value, and every branch starts with a unique marker, so a
    test that reads a name changes the output when its result changes.
    Every test uses a fresh condition variable unless it reads x or y, so
    every syntactic path is feasible.
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.constant = 0
        self.conds = 0
        self.markers = 0
        self.nested = False  # the template contains a for, with, or macro call
        self.imports = 0

    def test(self) -> str:
        if self.rng.random() < 0.1:
            return self.rng.choice(VARS)
        self.conds += 1
        return f"c{self.conds}"

    def branch(self, depth: int) -> str:
        self.markers += 1
        return f"<b{self.markers}>" + self.block(depth)

    def block(self, depth: int) -> str:
        return "".join(self.statement(depth) for _ in range(self.rng.randint(1, 3)))

    def statement(self, depth: int) -> str:
        kinds = ["set", "set", "set", "read", "read", "read", "copy", "call"]
        if self.rng.random() < 0.15:
            kinds += ["include", "include_nc", "import"]
        if depth < MAX_DEPTH:
            kinds += [
                "for",
                "with",
                "setblock",
                "filter",
                "callblock",
                "scope",
                "keep",
                "callkept",
            ]
            if self.conds < MAX_TESTS - 2:
                kinds += [
                    "if",
                    "if",
                    "if",
                    "if",
                    "ifall",
                    "ifall",
                    "ifall",
                    "ifall",
                    "carry",
                ]
        kind = self.rng.choice(kinds)
        var = self.rng.choice(VARS)
        if kind == "set":
            self.constant += 1
            return f"{{% set {var} = {self.constant} %}}"
        if kind == "read":
            return f"[{{{{ {var} }}}}]"
        if kind == "copy":
            return f"{{% set {var} = {self.rng.choice(VARS)} %}}[{{{{ {var} }}}}]"
        if kind == "call":
            self.nested = True
            return f"{{{{ m_{var}() }}}}"
        if kind == "include":
            self.nested = True
            return f"{{% include 'inc_{var}' %}}"
        if kind == "include_nc":
            self.nested = True
            return f"{{% include 'inc_{var}' without context %}}"
        if kind == "import":
            self.nested = True
            self.imports += 1
            alias = f"mod{self.imports}"
            return (
                f"{{% import 'mod_{var}' as {alias} with context %}}"
                f"<m{var}:{{{{ {alias}.value }}}}>"
            )
        if kind == "for":
            self.nested = True
            items = "[0, 1]" if self.rng.random() < 0.5 else "[0]"
            return f"{{% for i in {items} %}}{self.block(depth + 1)}{{% endfor %}}"
        if kind == "keep":
            self.nested = True
            return self.statement_of("keep", var)
        if kind == "callkept":
            self.nested = True
            return "{% if ns.f %}{{ ns.f() }}{% endif %}"
        if kind == "with":
            self.nested = True
            return f"{{% with %}}{self.block(depth + 1)}{{% endwith %}}"
        if kind == "setblock":
            self.nested = True
            inner = self.block(depth + 1)
            return f"{{% set {var} %}}{inner}{{% endset %}}[{{{{ {var} }}}}]"
        if kind == "filter":
            self.nested = True
            return f"{{% filter upper %}}{self.block(depth + 1)}{{% endfilter %}}"
        if kind == "callblock":
            self.nested = True
            return f"{{% call m_wrap() %}}{self.block(depth + 1)}{{% endcall %}}"
        if kind == "scope":
            self.nested = True
            return (
                f"{{% autoescape false %}}{self.block(depth + 1)}{{% endautoescape %}}"
            )
        if kind == "ifall":
            return self.if_all(depth, var)
        if kind == "carry":
            # Added after the defects of patches v2 and v3 were found by hand
            # and by review: a frame that runs twice calls a kept macro, sets
            # the name in every branch, then keeps a new macro that reads it.
            # The frame is a loop body, or a with, filter, set block, or loop
            # else frame inside a loop, or the second of two sibling frames.
            self.nested = True
            filler = self.block(depth + 1) if self.rng.random() < 0.5 else ""
            keep = self.statement_of("keep", var)
            if_all = self.if_all(depth + 1, var)
            body = f"{{% if ns.f %}}{{{{ ns.f() }}}}{{% endif %}}{filler}{if_all}{keep}"
            shape = self.rng.choice(
                ("loop", "with", "filter", "setblock", "else", "sibling")
            )
            if shape == "with":
                body = f"{{% with %}}{body}{{% endwith %}}"
            elif shape == "filter":
                body = f"{{% filter upper %}}{body}{{% endfilter %}}"
            elif shape == "setblock":
                body = f"{{% set s %}}{body}{{% endset %}}{{{{ s }}}}"
            elif shape == "else":
                body = f"{{% for j in [] %}}{{% else %}}{body}{{% endfor %}}"
            elif shape == "sibling":
                with_body = f"{{% with %}}{body}{{% endwith %}}"
                return with_body + with_body
            return f"{{% for i in [0, 1] %}}{body}{{% endfor %}}"
        parts = [f"{{% if {self.test()} %}}{self.branch(depth + 1)}"]
        for _ in range(self.rng.choice((0, 0, 1, 1, 2))):
            if self.conds < MAX_TESTS:
                parts.append(f"{{% elif {self.test()} %}}{self.branch(depth + 1)}")
        if self.rng.random() < 0.65:
            parts.append(f"{{% else %}}{self.branch(depth + 1)}")
        return "".join(parts) + "{% endif %}"

    def statement_of(self, kind: str, var: str) -> str:
        if kind == "keep":
            if self.rng.random() < 0.5:
                return (
                    f"{{% macro k() %}}<k:{{{{ {var} }}}}>{{% endmacro %}}"
                    "{% set ns.f = k %}"
                )
            return f"{{% call m_keep() %}}<k:{{{{ {var} }}}}>{{% endcall %}}"
        raise ValueError(kind)

    def if_all(self, depth: int, var: str) -> str:
        """An if statement whose every branch sets var; one branch in four
        does something else first."""

        def setting_branch() -> str:
            self.markers += 1
            self.constant += 1
            before = self.block(depth + 1) if self.rng.random() < 0.25 else ""
            after = self.block(depth + 1) if self.rng.random() < 0.3 else ""
            return (
                f"<b{self.markers}>{before}{{% set {var} = {self.constant} %}}{after}"
            )

        parts = [f"{{% if {self.test()} %}}{setting_branch()}"]
        for _ in range(self.rng.choice((0, 0, 1, 2))):
            if self.conds < MAX_TESTS:
                parts.append(f"{{% elif {self.test()} %}}{setting_branch()}")
        parts.append(f"{{% else %}}{setting_branch()}")
        return "".join(parts) + "{% endif %}"


def generate(count: int, seed: int) -> list:
    """Return ``count`` distinct templates."""
    rng = random.Random(seed)
    templates = []
    seen = set()
    while len(templates) < count:
        gen = Generator(rng)
        body = gen.block(0)
        prefix = (MACROS if "m_x" in body or "m_y" in body else "") + (
            WRAP if "m_wrap" in body else ""
        )
        prefix = (KEEP if "ns.f" in body or "m_keep" in body else "") + prefix
        if prefix + body in seen:
            continue
        seen.add(prefix + body)
        templates.append(
            {"source": prefix + body, "nested": gen.nested, "conds": gen.conds}
        )
    return templates


class Mark:
    """A falsy value with a distinctive text. Any use of it shows."""

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return "#MARK#"


def measure(templates: list) -> dict:
    import jinja2
    from jinja2 import DictLoader
    from jinja2 import Environment
    from jinja2 import meta
    from jinja2.runtime import Context

    class MarkingContext(Context):
        """Answer lookups of one name by the template under test (which has
        no name) with a Mark. Included and imported templates have names,
        so their own lookups get the real value.
        """

        marked = None

        def resolve_or_missing(self, key):
            if key == MarkingContext.marked and self.name is None:
                return Mark()
            return super().resolve_or_missing(key)

    env = Environment(loader=DictLoader(LOADED))
    env.context_class = MarkingContext

    def render(template, context: dict) -> str:
        try:
            text = template.render(context)
        except Exception as error:  # an error is an observable result too
            text = f"ERROR {type(error).__name__}"
        return ADDRESS.sub(" at 0x?", text)

    for item in templates:
        source = item["source"]
        item["reported"] = sorted(
            meta.find_undeclared_variables(env.parse(source)) & set(VARS)
        )
        template = env.from_string(source)
        conds = [f"c{n + 1}" for n in range(item["conds"])]
        paths = ["".join(bits) for bits in itertools.product("01", repeat=len(conds))]
        outputs = {}
        contexts = {}
        for present in PRESENCE:
            for path in paths:
                context = {name: bit == "1" for name, bit in zip(conds, path)}
                context.update({v: v.upper() for v in present})
                contexts[f"{present}:{path}"] = context
                outputs[f"{present}:{path}"] = render(template, context)
        item["outputs"] = outputs
        # v is used when marking the template's own lookups of v changes an output
        used = []
        for v in VARS:
            for key, context in contexts.items():
                if v in key.split(":")[0]:
                    MarkingContext.marked = v
                    marked = render(template, context)
                    MarkingContext.marked = None
                    if marked != outputs[key]:
                        used.append(v)
                        break
        item["used"] = used
        # v is needed when removing it from some context changes some output
        item["needed"] = sorted(
            v
            for v in VARS
            if any(
                outputs[f"{present}:{path}"]
                != outputs[f"{present.replace(v, '')}:{path}"]
                for present in PRESENCE
                if v in present
                for path in paths
            )
        )
    return {
        "jinja2": jinja2.__version__,
        "jinja2_file": jinja2.__file__,
        "templates": templates,
    }


def properties(dump: dict, oracle: dict, label: str) -> None:
    """Judge ``reported`` of ``dump`` against ``needed`` of ``oracle``.

    The oracle is always the reference build. ``meta`` mirrors the compiler,
    so a build's own renders agree with its own analysis even when both are
    wrong; only another build's renders can expose that.
    """
    pairs = list(zip(dump["templates"], oracle["templates"]))
    for group, wanted in (
        ("flat (no nested scope)", False),
        ("with nested scopes", True),
    ):
        items = [
            (t["reported"], o["used"], o["needed"], t["source"])
            for t, o in pairs
            if t["nested"] == wanted
        ]
        missed = [i for i in items if set(i[1]) - set(i[0])]
        unused = sum(len(set(i[0]) - set(i[1])) for i in items)
        exact = sum(i[0] == i[1] for i in items)
        include_only = sum(bool(set(i[2]) - set(i[1])) for i in items)
        print(
            f"  {label:10} {group:23} templates {len(items):5}"
            f"   misses a used lookup {len(missed):4}"
            f"   names reported but unused {unused:5}   exact {exact:5}"
            f"   needed only by an included template {include_only:4}"
        )
        for reported, used, _, source in sorted(missed, key=lambda i: len(i[3]))[:2]:
            print(f"      missed example: reported {reported} used {used}  {source}")


def compare(reference: dict, candidate: dict) -> int:
    ref, cand = reference["templates"], candidate["templates"]
    if [t["source"] for t in ref] != [t["source"] for t in cand]:
        sys.exit("the two dumps were generated with different templates")
    print(
        f"reference: {reference.get('jinja2_file', reference['jinja2'])}"
        f"\ncandidate: {candidate.get('jinja2_file', candidate['jinja2'])}"
    )
    print(f"templates: {len(ref)}, renders: {sum(len(t['outputs']) for t in ref)}")

    print("\nRendering differences (candidate against reference)")
    differing = [(r, c) for r, c in zip(ref, cand) if r["outputs"] != c["outputs"]]
    flat = sum(not r["nested"] for r, _ in differing)
    print(
        f"  templates whose output differs: {len(differing)}"
        f"  (flat: {flat}, with nested scopes: {len(differing) - flat})"
    )
    for r, c in sorted(differing, key=lambda pair: len(pair[0]["source"]))[:4]:
        key = next(k for k in r["outputs"] if r["outputs"][k] != c["outputs"][k])
        print(f"      {r['source']}")
        print(
            f"        context {key}: reference {r['outputs'][key]!r}"
            f"  candidate {c['outputs'][key]!r}"
        )

    print("\nResult of find_undeclared_variables (x and y only)")
    changed = [(r, c) for r, c in zip(ref, cand) if r["reported"] != c["reported"]]
    fewer = sum(set(c["reported"]) < set(r["reported"]) for r, c in changed)
    print(
        f"  templates whose result differs: {len(changed)}"
        f"  (candidate reports fewer names: {fewer}, other: {len(changed) - fewer})"
    )

    print(
        "\nOracle properties"
        " (needed = names whose presence changes an output of the reference build)"
    )
    properties(reference, reference, "reference")
    properties(candidate, reference, "candidate")
    return len(differing)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    dump = sub.add_parser("dump")
    dump.add_argument("out")
    dump.add_argument("--count", type=int, default=12000)
    dump.add_argument("--seed", type=int, default=593)
    comp = sub.add_parser("compare")
    comp.add_argument("reference")
    comp.add_argument("candidate")
    args = parser.parse_args()

    if args.command == "dump":
        result = measure(generate(args.count, args.seed))
        with open(args.out, "w") as f:
            json.dump(result, f)
        print(
            f"jinja2 {result['jinja2']} from {result['jinja2_file']}:"
            f" measured {len(result['templates'])} templates -> {args.out}"
        )
    else:
        with open(args.reference) as f:
            reference = json.load(f)
        with open(args.candidate) as f:
            candidate = json.load(f)
        compare(reference, candidate)


if __name__ == "__main__":
    main()
