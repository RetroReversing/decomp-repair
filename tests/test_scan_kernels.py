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


def _params(t, a, r):
    return [(t, a, left, right) for left, right in (("{", "}"), ("(", ")"), ("{", "{"), ("{}", "}"))]


FOURTH_BATCH = [
    ("guard_compare_first", "_close", _params),
    ("guard_symbol_pointer", "_close", _params),
    ("guarded_offset_index", "_close", lambda t, a, r: [(t, a)]),
    ("guarded_offset_index", "_paren_close", lambda t, a, r: [(t, a)]),
    ("join_skip_width_conflict", "_close", lambda t, a, r: _params(t, a, r) + [(t, a)]),
    ("guarded_constant_ternary", "_condition_end", lambda t, a, r: [(t, a)]),
    ("interpreter_arm_steps", "_balanced", lambda t, a, r: [(t, a)]),
    ("goto_arm_tail_inline", "_end_of_block", lambda t, a, r: [(t, a, r.randint(-2, len(t) + 3))]),
    ("join_store_split_repairs", "_block_end", lambda t, a, r: [(t, a)]),
    ("gbi_macro_commands", "_match_open", lambda t, a, r: [(t, a)]),
    ("invariant_shift_local", "_block_open", lambda t, a, r: [(t, a, r.randint(-2, len(t) + 2))]),
]


def test_the_fourth_batch_of_own_scans_match_their_plain_loops_on_random_text():
    import importlib

    rng = random.Random(55)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\n", ";", "é", "𝄞", "((", "}}"]
    for module_name, function, build in FOURTH_BATCH:
        module = importlib.import_module(f"decomprepair.{module_name}")
        twin = getattr(module, "_python_" + function.lstrip("_"))
        kernel_backed = getattr(module, function)
        assert kernel_backed is not twin, f"{module_name}.{function} did not take the kernel"
        for _ in range(4000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
            where = rng.randint(-3, len(text) + 2)
            for args in build(text, where, rng):
                assert _outcome(kernel_backed, *args) == _outcome(twin, *args), (module_name, function, args)


FIFTH_BATCH = [
    ("guard_counter_compare", "_close", _params),
    ("guarded_do_while_loop", "_close", _params),
    ("halfword_countdown_shapes", "_close", lambda t, a, r: _params(t, a, r) + [(t, a)]),
    ("last_use_shift_in_place", "_close", lambda t, a, r: _params(t, a, r) + [(t, a)]),
    ("inline_param_width", "_close", lambda t, a, r: [(t, a)]),
    ("guarded_do_to_for", "_call_end", lambda t, a, r: [(t, a)]),
    ("halfword_position_shift", "_group_start", lambda t, a, r: [(t, a)]),
    ("join_initializer_sink_repairs", "_enclosing", lambda t, a, r: [(t, a, r.randint(-2, len(t) + 2))]),
    ("label_entry_initializer_repairs", "_block_start", lambda t, a, r: [(t, a, r.randint(-2, len(t) + 2))]),
    ("dead_pointer_address_reuse", "_enclosing", lambda t, a, r: [(t, a, r.randint(-2, len(t) + 2))]),
]


def test_the_fifth_batch_of_own_scans_match_their_plain_loops_on_random_text():
    import importlib

    rng = random.Random(66)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\n", ";", "é", "𝄞", "((", "}}"]
    for module_name, function, build in FIFTH_BATCH:
        module = importlib.import_module(f"decomprepair.{module_name}")
        twin = getattr(module, "_python_" + function.lstrip("_"))
        kernel_backed = getattr(module, function)
        assert kernel_backed is not twin, f"{module_name}.{function} did not take the kernel"
        for _ in range(4000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
            where = rng.randint(-3, len(text) + 2)
            for args in build(text, where, rng):
                assert _outcome(kernel_backed, *args) == _outcome(twin, *args), (module_name, function, args)


def _three(t, a, r):
    return [(t, a, r.randint(-2, len(t) + 3))]


def _four(t, a, r):
    return [(t, a, r.randint(-2, len(t) + 3), r.randint(-1, len(t) + 2))]


SIXTH_BATCH = [
    ("address_param_copy_repairs", "_block_of", _four),
    ("arm_pointer_parameter_copy", "_enclosing_end", _four),
    ("constant_flag_hoist", "_block_start", _three),
    ("duplicate_return_node_repairs", "_opening", lambda t, a, r: [(t, a)]),
    ("loaded_pointer_reuse_repairs", "_block", lambda t, a, r: [(t, a)]),
    ("float_arm_roles", "_opening_brace", lambda t, a, r: [(t, a)]),
    ("float_clamp_reads", "_close", lambda t, a, r: [(t, a)]),
    ("goto_label_else_arm", "_enclosing_close", _four),
    ("literal_mask_conjunction", "_matching", lambda t, a, r: [(t, a)]),
    ("expression_terms", "_match", lambda t, a, r: [(t, a)]),
    ("expression_terms", "_top_split", lambda t, a, r: [(t, a, r.randint(-2, len(t) + 3), sep) for sep in (",", ";", "(", ",,")]),
    ("join_call_arm_copy", "_statement_end", lambda t, a, r: [(t, a)]),
    ("goto_structure_repairs", "_simple_end", _three),
    ("load_above_global_store", "_statement_end", lambda t, a, r: [(t, a)]),
    ("call_index_temps_pointer", "_expr_end", lambda t, a, r: [(t, a)]),
    ("late_aggregate_scope", "_depth_one", _three),
    ("copy_compare_fence", "_boundaries", lambda t, a, r: [(t,)]),
    ("deref_sum_locals", "_statement_start", _three),
    ("field_array_base_local", "_statement_start", _three),
    ("arm_reload_restore", "_split", _three),
    ("increment_old_value_copy", "_segments", _three),
]


def test_the_sixth_batch_of_own_scans_match_their_plain_loops_on_random_text():
    import importlib

    rng = random.Random(77)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\t", "\n", ";", ",", "é", "𝄞", "((", "}}", "; "]
    for module_name, function, build in SIXTH_BATCH:
        module = importlib.import_module(f"decomprepair.{module_name}")
        twin = getattr(module, "_python_" + function.lstrip("_"))
        kernel_backed = getattr(module, function)
        assert kernel_backed is not twin, f"{module_name}.{function} did not take the kernel"
        for _ in range(4000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
            where = rng.randint(-3, len(text) + 2)
            for args in build(text, where, rng):
                assert _outcome(kernel_backed, *args) == _outcome(twin, *args), (module_name, function, args)


SEVENTH_BATCH = [
    ("loop_vector_shapes", "_matching", lambda t, a, r: [(t, a)]),
    ("m2c_undeclared_drafts", "_open", lambda t, a, r: [(t, a)]),
    ("masked_compare_signed_cast", "_open_of", lambda t, a, r: [(t, a)]),
    ("narrow_store_width", "_statement_end", lambda t, a, r: [(t, a)]),
    ("nested_join_hoist_repairs", "_enclosing_block", _three),
    ("or_chain_order_repairs", "_close", lambda t, a, r: [(t, a)]),
    ("outer_cursor_entry_copy_repairs", "_block_head", lambda t, a, r: [(t, a)]),
    ("paired_statement_moves", "_statement_end", _three),
    ("param_loop_carrier", "_block_start", _three),
    ("pointer_pair_loop", "_span", lambda t, a, r: [(t, a, "(", ")"), (t, a, "{", "}"), (t, a, "{", "{"), (t, a, "{}", "}")]),
    ("product_split_sum", "_group_start", lambda t, a, r: [(t, a)]),
    ("product_split_sum", "_group_end", lambda t, a, r: [(t, a)]),
    ("queue_cursor_index_repairs", "_block_end", _three),
    ("quotient_chain_stage", "_open", lambda t, a, r: [(t, a)]),
    ("record_row_member", "_expression_end", lambda t, a, r: [(t, a)]),
    ("result_weight_scope", "_close", _params),
    ("retry_goto_scope_repairs", "_close", lambda t, a, r: _params(t, a, r) + [(t, a)]),
    ("run_weight_scope", "_match", _params),
    ("saved_register_cascade", "_block_of", _four),
    ("signed_shift_operand", "_open_of", lambda t, a, r: [(t, a)]),
    ("source_variable_reuse_repairs", "_block_end", _three),
]


def test_the_seventh_batch_of_own_scans_match_their_plain_loops_on_random_text():
    import importlib

    rng = random.Random(88)
    pieces = ["(", ")", "{", "}", "[", "]", "a", " ", "\t", "\n", ";", ",", "é", "𝄞", "((", "}}", "; "]
    for module_name, function, build in SEVENTH_BATCH:
        module = importlib.import_module(f"decomprepair.{module_name}")
        twin = getattr(module, "_python_" + function.lstrip("_"))
        kernel_backed = getattr(module, function)
        assert kernel_backed is not twin, f"{module_name}.{function} did not take the kernel"
        for _ in range(4000):
            text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 30)))
            where = rng.randint(-3, len(text) + 2)
            for args in build(text, where, rng):
                assert _outcome(kernel_backed, *args) == _outcome(twin, *args), (module_name, function, args)
