"""The offset-to-pointer loops of a loader, written as calls of one inline helper."""
from decomprepair import rebase_loop_helper as repair

LOOP = '''        {i} = 0;
        if ({i} < count) {{
            do {{ cursor{n} = M2C_FIELD(arg0, void ***, {at}); }} while (0);
            do {{
                value{n} = *cursor{n};
                do {{ {i} += 1; }} while (0);
                if (value{n} != NULL) {{
                    *cursor{n} = (s32)value{n} + (s32)arg0;
                }}
                cursor{n} += 1;
            }} while ({i} < count);
        }}
'''

SOURCE = '''s32 load_bank(void *arg0) {
    s32 count;
    s32 var_a0;
    s32 var_a1;
    void **cursor0;
    void **cursor1;
    void **cursor2;
    void *value0;
    void *value1;
    void *value2;

    count = M2C_FIELD(arg0, s32 *, 4);
    if (M2C_FIELD(arg0, s32 *, 8) == 0) {
        M2C_FIELD(arg0, s32 *, 8) = 1;
        var_a0 = 0;
        cursor0 = arg0 + 0xC;
        do {
            value0 = *cursor0;
            var_a0 += 1;
            if (value0 != NULL) {
                *cursor0 = (s32)value0 + (s32)arg0;
            }
            cursor0 += 1;
        } while (var_a0 < 7);
''' + LOOP.format(i='var_a1', n=1, at='0xC') + LOOP.format(i='var_a1', n=2, at='0x10') + '''    }
    return count;
}
'''


def children(source):
    return dict(repair.variants(source, 'load_bank'))


def test_every_loop_becomes_a_call_and_its_names_go():
    out = children(SOURCE)
    assert set(out) == set(repair.FAMILIES)
    child = out[repair.BEFORE]
    assert 'static inline void __repair_rebase(s32 *list, s32 n, s32 base) {\n    s32 offset = base;' in child
    body = child[child.index('s32 load_bank'):]
    assert body.count('__repair_rebase((s32 *)') == 3
    assert '__repair_rebase((s32 *)(arg0 + 0xC), 7, __repair_base);' in body
    assert '__repair_rebase((s32 *)(M2C_FIELD(arg0, void ***, 0x10)), count, __repair_base);' in body
    assert 'do' not in body and 'cursor' not in body and 'value' not in body and 'var_a' not in body
    assert body.index('__repair_base = (s32)arg0;') < body.index('if (')


def test_base_beside_the_first_call_or_passed_straight():
    out = children(SOURCE)
    inner = out[repair.INNER]
    assert inner.index('if (M2C_FIELD') < inner.index('__repair_base = (s32)arg0;')
    assert '__repair_base' not in out[repair.DIRECT]
    assert '7, (s32)arg0);' in out[repair.DIRECT]


def test_a_cursor_read_afterwards_is_left_alone():
    assert not children(SOURCE.replace('return count;', 'return (s32)*cursor0;'))


def test_a_counter_that_does_not_start_at_zero_is_left_alone():
    changed = SOURCE.replace('        var_a0 = 0;\n        cursor0', '        var_a0 = 1;\n        cursor0')
    assert '__repair_rebase((s32 *)(arg0 + 0xC)' not in children(changed).get(repair.BEFORE, '')


def test_an_unguarded_loop_with_a_variable_bound_is_left_alone():
    changed = SOURCE.replace('var_a0 < 7', 'var_a0 < count')
    assert '__repair_rebase((s32 *)(arg0 + 0xC)' not in children(changed).get(repair.BEFORE, '')
