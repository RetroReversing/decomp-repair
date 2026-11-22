from decomprepair.loop_weight_repairs import COUNTER_HOIST, variants

SOURCE = """
extern void sink(int);
void f(int size) {
    int index;
    index = 7;
    if (size > 0) {
        index = 0;
        do {
            sink(index);
            index++;
        } while (index < size);
    }
}
"""


def test_plain_hoist_does_not_require_a_one_shot_scope():
    candidates = [candidate for family, candidate in variants(SOURCE, 'f') if family == COUNTER_HOIST]
    assert len(candidates) == 1
    assert '    index = 0;\n    if (size > 0)' in candidates[0]
    assert '__repair_loop_weight' not in candidates[0]


def test_plain_hoist_requires_a_dead_counter_at_guard_entry():
    live = SOURCE.replace('    }\n}', '    }\n    sink(index);\n}')
    assert all(family != COUNTER_HOIST for family, _ in variants(live, 'f'))


def test_hoist_respects_an_unbraced_parent_and_external_jump():
    nested = SOURCE.replace('    if (size > 0)', '    if (size != 2)\n        if (size > 0)')
    incoming = SOURCE.replace('    if (size > 0)', '    if (size == 2) goto entry;\n    if (size > 0)')
    incoming = incoming.replace('        index = 0;', '        entry: ;\n        index = 0;')
    for source in (nested, incoming):
        assert all(family != COUNTER_HOIST for family, _ in variants(source, 'f'))
