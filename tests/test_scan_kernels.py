"""The typed scans (`_scan.pyx`, built by native_build.py) answer exactly what the plain Python ones answer."""
import random

import pytest

from decomprepair import pattern_repairs

scan = pytest.importorskip("decomprepair._scan", reason="the typed scans are not built")


def _outcome(function, *arguments):
    try:
        return function(*arguments)
    except Exception as error:  # the plain scan raises for a start far before the text: so must the typed one
        return type(error)


def test_close_matches_the_plain_scan_on_random_text():
    rng = random.Random(7)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\n", "é", "𝄞", "((", "))"]
    for _ in range(20000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
        start = rng.randint(-3, len(text) + 2)
        for left, right in (("(", ")"), ("{", "}"), ("[", "]"), ("(", "("), ("({", ")}")):
            assert _outcome(scan.close, text, start, left, right) == _outcome(
                pattern_repairs._close, text, start, left, right), (text, start, left, right)


def test_the_library_uses_the_typed_scan_when_it_is_built():
    assert pattern_repairs.close is scan.close


def test_the_c_scan_walkers_match_the_plain_ones_on_random_text():
    from decomprepair import c_scan

    rng = random.Random(8)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\n", ";", "é", "if (a) ", "for (;;) ", "do "]
    for _ in range(20000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
        n = len(text)
        a, b = rng.randint(-3, n + 3), rng.randint(-3, n + 3)
        for left, right in (("{", "}"), ("(", ")"), ("{", "{"), ("{}", "}")):
            assert _outcome(scan.c_close, text, a, left, right) == _outcome(c_scan._close, text, a, left, right), (
                text, a, left, right)
        assert _outcome(scan.c_enclosing_block, text, a, b) == _outcome(c_scan._enclosing_block, text, a, b), (text, a, b)
        assert _outcome(scan.c_header_before, text, a) == _outcome(c_scan._header_before, text, a), (text, a)


def test_the_library_uses_the_typed_c_scan_walkers_when_they_are_built():
    from decomprepair import c_scan

    assert (c_scan.close, c_scan.enclosing_block, c_scan.header_before, c_scan.own_loop_statements) == (
        scan.c_close, scan.c_enclosing_block, scan.c_header_before, scan.c_own_loop_statements)


def test_own_loop_statements_matches_the_plain_scan_on_random_text():
    from decomprepair import c_scan

    rng = random.Random(12)
    pieces = ["(", ")", "{", "}", ";", "continue;", "break;", " ", "\n", "for (;;) {", "while (a) {", "do {", "switch (a) {",
              "if (b) {", "x", "_continue", "continue_", "é", "}"]
    for _ in range(20000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 24)))
        n = len(text)
        lo, hi = rng.randint(-2, n + 2), rng.randint(-2, n + 2)
        for word in ("continue", "break", ""):
            assert _outcome(scan.c_own_loop_statements, text, lo, hi, word) == _outcome(
                c_scan._own_loop_statements, text, lo, hi, word), (text, lo, hi, word)


# Modules that wrote their own bracket matcher and now answer with the typed kernel (_scan.close_if / close_every).
# (module, function, fixed brackets or None when left/right are parameters)
OWN_MATCHERS = [
    ("arm_invariant_sink", "_close", ("{", "}")),
    ("entry_guard_sink", "_close", ("{", "}")),
    ("flag_exit_repairs", "_close", ("{", "}")),
    ("arm_label_share_repairs", "_match", ("{", "}")),
    ("entry_parameter_copy_repairs", "_matching", ("{", "}")),
    ("call_test_argument_stage", "_close", ("(", ")")),
    ("arm_shared_arg_inline", "_close", ("{", "}")),
    ("block_temp_role_merge", "_close", None),
    ("chain_load_scope", "_close", None),
    ("debris", "_close", None),
]


def test_each_modules_own_bracket_matcher_matches_its_plain_loop_on_random_text():
    import importlib

    rng = random.Random(21)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\n", ";", "é", "𝄞", "((", "}}"]
    for module_name, function, brackets in OWN_MATCHERS:
        module = importlib.import_module(f"decomprepair.{module_name}")
        twin = getattr(module, "_python_" + function.lstrip("_"))
        kernel_backed = getattr(module, function)
        assert kernel_backed is not twin, f"{module_name} did not take the kernel"
        for _ in range(4000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
            start = rng.randint(-3, len(text) + 2)
            arguments = [(text, start)]
            if brackets is None:
                arguments = [(text, start, left, right)
                             for left, right in (("{", "}"), ("(", ")"), ("{", "{"), ("{}", "}"))]
                arguments.append((text, start))  # the module's own default brackets
            for args in arguments:
                assert _outcome(kernel_backed, *args) == _outcome(twin, *args), (module_name, args)


# The second batch: the arguments differ by module, so each says which it takes.
#   start: (text, start)   params: (text, start, left, right)   opener: (text, at, opener)   limit: (text, start, limit)
MORE_MATCHERS = [
    ("arm_index_offsets", "_block_end", "start"),
    ("arm_input_result_merge", "_close", "params"),
    ("arm_input_result_merge", "_block_end", "limit"),
    ("branch_join_arm_rewrites", "_close", "params"),
    ("condition_value_reuse", "_close", "params"),
    ("branch_slot_scope", "_close", "params"),
    ("expression_locals", "close", "start"),
    ("else_if_arm_swap", "_close", "start"),
    ("else_arm_copy_split", "_match", "opener"),
    ("complement_late", "_block_end", "start"),
    ("branch_polarity_repairs", "_block_end", "start"),
]


def _arguments(kind, text, start, rng):
    if kind == "start":
        return [(text, start)]
    if kind == "params":
        return [(text, start, left, right) for left, right in (("{", "}"), ("(", ")"), ("{", "{"), ("{}", "}"))]
    if kind == "opener":
        return [(text, start, opener) for opener in ("{", "(", "[")]  # "[" is the twin's KeyError
    return [(text, start, rng.randint(-2, len(text) + 3))]


def test_the_second_batch_of_own_matchers_match_their_plain_loops_on_random_text():
    import importlib

    rng = random.Random(33)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\n", ";", "é", "𝄞", "((", "}}"]
    for module_name, function, kind in MORE_MATCHERS:
        module = importlib.import_module(f"decomprepair.{module_name}")
        twin = getattr(module, "_python_" + function.lstrip("_"))
        kernel_backed = getattr(module, function)
        assert kernel_backed is not twin, f"{module_name}.{function} did not take the kernel"
        for _ in range(4000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
            start = rng.randint(-3, len(text) + 2)
            for args in _arguments(kind, text, start, rng):
                assert _outcome(kernel_backed, *args) == _outcome(twin, *args), (module_name, function, args)


# The third batch: scans that run backwards to an opening bracket, and the block-end scans, each with its own arguments.
def _part(rng, text):
    from types import SimpleNamespace

    return SimpleNamespace(opening=rng.randint(-1, len(text) + 1), end=rng.randint(0, len(text) + 1))


THIRD_BATCH = [
    ("arm_pointer_split_repairs", "_open_of", lambda t, a, r: [(t, a)]),
    ("carried_store_arms_repairs", "_opening_brace", lambda t, a, r: [(t, a)]),
    ("compare_bias_fold", "_open_of", lambda t, a, r: [(t, a)]),
    ("constant_exit_return_repairs", "_opening", lambda t, a, r: [(t, a)]),
    ("call_pointer_dead_temp", "_block_of", lambda t, a, r: [(t, a, r.randint(-2, len(t) + 2), r.randint(0, len(t)))]),
    ("arm_scratch_block_locals", "_enclosing", lambda t, a, r: [(t, a)]),
    ("collapsed_guard_inplace_step", "_enclosing", lambda t, a, r: [(t, a, r.randint(-2, len(t) + 2))]),
    ("call_carrier_pointer_split", "_enclosing_block", lambda t, a, r: [(t, _part(r, t), a)]),
    ("compare_temp_cascade_inline", "_block_end", lambda t, a, r: [(t, a, r.randint(-2, len(t) + 3))]),
    ("else_tail_into_arms", "_block_end", lambda t, a, r: [(t, a, r.randint(-2, len(t) + 3))]),
]


def test_the_third_batch_of_own_scans_match_their_plain_loops_on_random_text():
    import importlib

    rng = random.Random(44)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\n", ";", "é", "𝄞", "((", "}}"]
    for module_name, function, build in THIRD_BATCH:
        module = importlib.import_module(f"decomprepair.{module_name}")
        twin = getattr(module, "_python_" + function.lstrip("_"))
        kernel_backed = getattr(module, function)
        assert kernel_backed is not twin, f"{module_name}.{function} did not take the kernel"
        for _ in range(4000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
            where = rng.randint(-3, len(text) + 2)
            for args in build(text, where, rng):
                assert _outcome(kernel_backed, *args) == _outcome(twin, *args), (module_name, function, args)
