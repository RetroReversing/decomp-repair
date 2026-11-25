"""loop_carried_temp_copy's pattern must not backtrack exponentially on a run of statements with no matching `if`."""
import importlib.util
import random
import time
from pathlib import Path

from decomprepair import loop_carried_temp_copy as family

PIECES = ["t = *p;", "x = y + 1;", " ", "\n", "if (t == 0) { } else { v = t; continue; }", "if (t != 0) { w = t; continue; }",
          "q = 3;", "{", "}", "if (a) { b = 1; }"]


def test_a_long_run_of_statements_without_the_if_is_fast():
    body = "void f(void) {\n    for (;;) {\n" + "".join(f"        D_8020{i:04X} = {i};\n" for i in range(60)) + "    }\n}\n"
    start = time.perf_counter()
    assert family.variants(body, "f") == []
    assert time.perf_counter() - start < 2


def test_the_pattern_matches_what_it_matched_before_the_backtracking_fix():
    old = Path(family.__file__).with_name("loop_carried_temp_copy.py").read_text()
    old = old.replace("(?P<mid>(?:[^;{{}}]*;)*?)", "(?P<mid>(?:\\s*[^;{{}}]*;)*?)")
    spec = importlib.util.spec_from_loader("lctc_old", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__package__"] = "decomprepair"
    exec(compile(old, "lctc_old", "exec"), module.__dict__)
    rng = random.Random(3)
    for _ in range(600):
        text = "".join(rng.choice(PIECES) for _ in range(rng.randint(1, 6)))
        assert [m.span() for m in family._PATTERN.finditer(text)] == [m.span() for m in module._PATTERN.finditer(text)], text
