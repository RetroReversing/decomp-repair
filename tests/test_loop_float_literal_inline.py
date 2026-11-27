"""loop_float_literal_inline: a literal m2c held in a local before a loop, written at the loop's reads."""
from decomprepair import loop_float_literal_inline as inline
from decomprepair import registry

SOURCE = '''s32 f(f32 *p, u32 n) {
    f32 temp_fs1;
    f32 total;
    u32 i;

    total = 0.0f;
    i = 0;
    temp_fs1 = 10000.0f;
loop_5:
    if (i < n) {
        total += p[0] / temp_fs1;
        total += p[1] / temp_fs1;
        p += 4;
        i += 1;
        goto loop_5;
    }
    return (s32) total;
}
'''


def test_the_goto_loop_and_the_literal_change_together():
    child = dict(inline.variants(SOURCE, 'f'))[inline.FAMILY + '_break']
    assert 'temp_fs1' not in child and 'goto' not in child and 'loop_5' not in child
    assert 'while (1) {\n    if (!(i < n)) {\n        break;\n    }\n        total += p[0] / 10000.0f;' in child
    assert child.count('10000.0f') == 2


def test_a_real_loop_only_takes_the_literal():
    loop = SOURCE.replace('loop_5:\n    if (i < n) {', '    while (i < n) {').replace('        goto loop_5;\n', '')
    out = dict(inline.variants(loop, 'f'))
    assert list(out) == [inline.FAMILY]
    assert 'temp_fs1' not in out[inline.FAMILY] and out[inline.FAMILY].count('10000.0f') == 2


def test_nothing_for_a_written_local_or_one_no_loop_reads():
    assert inline.variants(SOURCE.replace('        p += 4;', '        temp_fs1 = 2.0f;\n        p += 4;'), 'f') == []
    assert inline.variants(SOURCE.replace('        p += 4;', '        use(&temp_fs1);\n        p += 4;'), 'f') == []
    outside = SOURCE.replace('p[0] / temp_fs1', 'p[0]').replace('p[1] / temp_fs1', 'p[1]').replace(
        '(s32) total', '(s32) (total * temp_fs1)')
    assert inline.variants(outside, 'f') == []


def test_a_body_with_its_own_break_keeps_its_goto_loop():
    guarded = SOURCE.replace('        p += 4;', '        if (total > 1.0f) {\n            break;\n        }\n        p += 4;')
    assert inline.FAMILY + '_break' not in dict(inline.variants(guarded, 'f'))


def test_a_one_shot_scope_is_not_a_loop():
    scoped = SOURCE.replace('loop_5:\n    if (i < n) {', '    do {').replace('        goto loop_5;\n    }\n', '    } while (0);\n')
    assert inline.variants(scoped, 'f') == []


def test_it_is_declared_in_the_registry():
    assert any(r.module == 'loop_float_literal_inline' for r in registry.declared())
