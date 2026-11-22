import re

from decomprepair.arm_invariant_sink import FAMILY, variants

SOURCE = """s32 pick(s32 size, s32 tag) {
    s32 mask = gAlign[tag] - 1;
    s32 inverse = ~mask;
    if (tag == 45) {
        u32 old = gTop;
        u32 end = old - size;
        end -= end & mask;
        gTop = end;
        return end;
    } else {
        u32 old = gBottom;
        u32 start = (old + mask) & inverse;
        gBottom = start + size;
        return start;
    }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _found(source=SOURCE, name='pick'):
    return [text for family, text in variants(source, name) if family == FAMILY]


def test_the_value_only_the_else_arm_reads_heads_that_arm_in_a_scope():
    found = _found()
    scoped = [_flat(text) for text in found if 'do { inverse = ~mask; } while (0);' in text]
    assert scoped, found
    out = scoped[0]
    assert 's32 inverse = ~mask;' not in out and 'inverse = ~mask; if (tag' not in out
    # it is the arm's first statement: before the arm's own loads
    assert out.index('do { inverse = ~mask; } while (0);') < out.index('old = gBottom;')
    assert 's32 inverse;' in out[out.index('} else {'):]


def test_the_plain_move_is_offered_too():
    plain = [_flat(text) for text in _found() if 'do { inverse' not in text]
    assert any('inverse = ~mask; old = gBottom;' in text for text in plain)


def test_nothing_when_both_arms_read_it_or_it_reads_memory():
    both = SOURCE.replace('u32 end = old - size;', 'u32 end = (old - size) & inverse;')
    assert _found(both) == []
    memory = SOURCE.replace('s32 inverse = ~mask;', 's32 inverse = gInv[tag];')
    assert _found(memory) == []


def test_nothing_without_a_two_arm_branch_or_when_the_inputs_change_first():
    one_arm = SOURCE.replace('} else {', '}\n    {').replace('    {\n        u32 old = gBottom;', '    if (tag != 45) {\n        u32 old = gBottom;')
    assert _found(one_arm) == []
    changed = SOURCE.replace('    if (tag == 45) {', '    mask = mask + 1;\n    if (tag == 45) {', 1)
    assert _found(changed) == []
