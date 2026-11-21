from decomprepair.measured_global_rebase import variants

SOURCE = """
extern s8 lower;
extern s32 upper;
s32 setup(s8 enabled) {
    s8 *flag;
    s32 *state;
    s32 ok;
    flag = &lower;
    ok = 1;
    (*flag) = enabled;
    if (!enabled) {
        (*flag) = 0;
        ok = 0;
    }
    state = (s32 *)(flag + 0x24);
    *state = 0;
    return ok;
}
"""

ROWS = [
    ('<', 'lui $v1, %hi(upper)', ''),
    ('<', 'addiu $v1, $v1, %lo(upper)', ''),
    ('i', 'lbu $v0, -0x24($v1)', 'lbu $v0, ($v1)'),
]


def test_rebases_with_measured_address_distance_and_negative_use():
    [(family, candidate)] = variants(SOURCE, 'setup', '', ROWS, resolve={'lower': 0x100, 'upper': 0x124}.get)
    assert family == 'measured_global_rebase'
    assert candidate == SOURCE.replace('(s32 *)(flag + 0x24)', '(s32 *)((((u32)&upper) + ok) - ok)')


def test_rebase_requires_matching_symbols_and_stable_original_base():
    assert not variants(SOURCE, 'setup', '', ROWS, resolve={'lower': 0x100, 'upper': 0x128}.get)
    resolve = {'lower': 0x100, 'upper': 0x124}.get
    assert not variants(SOURCE, 'setup', '', ROWS[:2], resolve=resolve)
    assert not variants(SOURCE.replace('    (*flag) = enabled;', '    flag++;'), 'setup', '', ROWS, resolve=resolve)
    assert not variants(SOURCE.replace('    ok = 1;', '    if (enabled) ok = 1;'), 'setup', '', ROWS, resolve=resolve)


def test_rebase_rejects_shadowed_symbol():
    source = SOURCE.replace('s8 enabled)', 's8 enabled, s32 upper)')
    assert not variants(source, 'setup', '', ROWS, resolve={'lower': 0x100, 'upper': 0x124}.get)
