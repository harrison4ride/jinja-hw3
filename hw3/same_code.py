#!/usr/bin/env python3
"""Check that two Jinja builds generate the same Python code.

The script compiles every template of a differential dump (see
differential.py) and every template string in Jinja's own test files with
the jinja2 package on the import path, and writes a digest per template.
Run it once per build and compare the two output files:

  PYTHONPATH=<build A>/src python same_code.py DUMP.json TESTS_DIR OUT_A.json
  PYTHONPATH=<build B>/src python same_code.py DUMP.json TESTS_DIR OUT_B.json
  python same_code.py --compare OUT_A.json OUT_B.json

Equal code for a template means equal rendering for every context, so a
build that changes only meta cannot change what any of these templates
render, in sync or async mode.
"""

import ast
import hashlib
import json
import sys
from pathlib import Path


def test_templates(tests_dir: Path) -> list:
    """Collect string constants that parse as templates with a tag or variable."""
    from jinja2 import Environment

    env = Environment()
    found = set()
    for path in sorted(tests_dir.glob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
                if ("{%" in text or "{{" in text) and len(text) < 5000:
                    try:
                        env.parse(text)
                    except Exception:
                        continue
                    found.add(text)
    return sorted(found)


def digest_all(dump_path: str, tests_dir: str, out_path: str) -> None:
    import jinja2
    from jinja2 import Environment

    with open(dump_path) as f:
        sources = [t["source"] for t in json.load(f)["templates"]]
    sources += test_templates(Path(tests_dir))
    digests = {}
    for is_async in (False, True):
        env = Environment(enable_async=is_async)
        for source in sources:
            try:
                code = env.compile(source, raw=True)
            except Exception as error:  # a compile error is a result too
                code = f"ERROR {type(error).__name__}: {error}"
            key = f"{'async' if is_async else 'sync'}:{source}"
            digests[key] = hashlib.sha256(code.encode()).hexdigest()
    with open(out_path, "w") as f:
        json.dump({"jinja2": jinja2.__file__, "digests": digests}, f)
    print(
        f"{jinja2.__file__}: compiled {len(digests)} template/mode pairs -> {out_path}"
    )


def compare(a_path: str, b_path: str) -> None:
    with open(a_path) as f:
        a = json.load(f)
    with open(b_path) as f:
        b = json.load(f)
    assert a["digests"].keys() == b["digests"].keys(), "different template sets"
    differ = [k for k in a["digests"] if a["digests"][k] != b["digests"][k]]
    print(f"A: {a['jinja2']}\nB: {b['jinja2']}")
    print(f"template/mode pairs compiled: {len(a['digests'])}")
    print(f"pairs whose generated code differs: {len(differ)}")
    for key in differ[:5]:
        print(f"  {key[:200]}")


if __name__ == "__main__":
    if sys.argv[1] == "--compare":
        compare(sys.argv[2], sys.argv[3])
    else:
        digest_all(sys.argv[1], sys.argv[2], sys.argv[3])
