from decomprepair import branch_float_call_inline as repair

MACRO = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))\n'
SOURCE = MACRO + '''void use(void *, f32, f32, f32);
void f(void *p, int flag) {
    f32 a;
    f32 b;
    f32 c;
    f32 x;
    if (flag) {
        a = M2C_FIELD(p, f32 *, 4);
        b = x;
        c = 1.0f;
    } else {
        a = 90.0f - x;
        b = M2C_FIELD(p, f32 *, 8);
        c = 0.0f;
    }
    use(p, a, b, c);
}
'''


def test_shared_call_and_its_float_snapshots_are_inlined_together():
    children = repair.variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert 'use(p, (M2C_FIELD(p, f32 *, 4)), (x), 1.0f);' in text
    assert 'use(p, (90.0f - x), (M2C_FIELD(p, f32 *, 8)), 0.0f);' in text
    assert 'f32 a;' not in text and 'f32 b;' not in text


def test_do_not_move_reads_past_side_effects_or_changed_locals():
    assert repair.variants(SOURCE.replace('use(p, a, b, c);', 'use(p++, a, b, c);'), 'f') == []
    assert repair.variants(SOURCE.replace('use(p, a, b, c);', 'use(change(), a, b, c);'), 'f') == []
    assert repair.variants(SOURCE.replace('use(p, a, b, c);', 'use(*p, a, b, c);'), 'f') == []
    assert repair.variants(SOURCE.replace('b = x;', 'b = x++;'), 'f') == []
    assert repair.variants(SOURCE.replace('f32 x;', 'volatile f32 x;'), 'f') == []
    assert repair.variants(SOURCE.replace(MACRO, '#define M2C_FIELD(a,b,c) side_effect()\n'), 'f') == []
    assert repair.variants(SOURCE, 'f', '#define x side_effect()') == []
    assert repair.variants(SOURCE, 'f', '#define p side_effect()') == []
    assert repair.variants(SOURCE.replace('use(p, a, b, c);', 'use(p, a /* keep */, b, c);'), 'f') == []


def test_a_snapshot_is_not_moved_past_an_assignment_to_its_input():
    source = SOURCE.replace('a = M2C_FIELD(p, f32 *, 4);\n        b = x;',
                            'a = x;\n        x = 2.0f;\n        b = x;')
    for _, text in repair.variants(source, 'f'):
        assert 'a = x;' in text
