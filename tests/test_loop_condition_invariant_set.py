"""A loop-invariant value set before a do-while and read only in its test, assigned inside the test."""
from decomprepair import registry
from decomprepair.loop_condition_invariant_set import FAMILY, variants

FILL = '''void f(u16 *tab, u32 *sym, u32 *len, u32 ent, u32 y, u32 k) {
    u32 a;
    u16 *sb;

    sb = tab + (ent >> 7);
    a = (ent >> 4) & 7;
    do {
        sb[y] = (sym[k] << 7) + len[k];
        y += 1 << len[k];
    } while ((y >> a) == 0);
}
'''


def test_the_shift_amount_goes_into_the_test():
    # a 681-instruction N64 decoder: the hoisted shift amount came after a loop-made copy, 85 -> 70
    kids = variants(FILL, 'f')
    assert [family for family, _ in kids] == [FAMILY]
    text = kids[0][1]
    assert '} while ((y >> (a = (ent >> 4) & 7)) == 0);' in text
    assert '    a = (ent >> 4) & 7;\n' not in text
    assert '    sb = tab + (ent >> 7);\n    do {' in text


def test_a_value_the_body_reads_or_changes_stays():
    read = FILL.replace('y += 1 << len[k];', 'y += a;')
    assert variants(read, 'f') == []
    changed = FILL.replace('y += 1 << len[k];', 'y += 1 << len[k]; ent++;')
    assert variants(changed, 'f') == []


def test_a_call_or_a_statement_between_that_changes_its_inputs_stays():
    called = FILL.replace('a = (ent >> 4) & 7;', 'a = g(ent);')
    assert variants(called, 'f') == []
    between = FILL.replace('    do {', '    ent = 3;\n    do {', 1)
    assert variants(between, 'f') == []


def test_the_module_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'loop_condition_invariant_set')
    assert registry.problems(repair) == [] and FAMILY in repair.families
