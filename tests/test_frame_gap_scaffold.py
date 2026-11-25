"""frame_gap_scaffold: an unused array of the missing size when the frame is the only difference."""
from decomprepair import frame_gap_scaffold as scaffold

SOURCE = '''void g(char *, f32 *);
s32 f(s32 n) {
    f32 v[4];
    char text[0x10];
    s32 i;

    g(text, v);
    for (i = 0; i < n; i++) {
        v[0] += 1.0f;
    }
    return i;
}
'''


def rows(target, candidate, markers=('s', 's')):
    return [(markers[0], f'addiu $sp, $sp, -{target}', f'addiu $sp, $sp, -{candidate}'),
            (markers[1], 'sw $ra, 0x2c($sp)', 'sw $ra, 0x1c($sp)')]


def test_the_gap_is_read_from_the_frame_rows_when_only_stack_rows_differ():
    assert scaffold.gap(rows(0x58, 0x38)) == 0x20
    assert scaffold.gap(rows('0x58', '0x38', ('s', 'r'))) == 0
    assert scaffold.gap(rows(0x38, 0x58)) == 0
    assert scaffold.gap(rows(0x3C, 0x38)) == 0
    assert scaffold.gap([]) == 0


def test_an_array_of_the_gap_is_declared_at_each_position_of_the_declarations():
    out = scaffold.from_rows(SOURCE, 'f', rows('0x58', '0x38'))
    assert {family for family, _ in out} == {scaffold.FAMILY}
    texts = [child for _, child in out]
    first = SOURCE.replace('s32 f(s32 n) {\n', 's32 f(s32 n) {\n    char frame_pad[32];\n')
    last = SOURCE.replace('    s32 i;\n', '    s32 i;\n    char frame_pad[32];\n')
    assert first in texts and last in texts
    assert any('s32 frame_pad[8];' in text for text in texts)
    assert len(texts) == len(set(texts))


def test_nothing_when_other_rows_differ_or_the_function_has_the_array_already():
    assert scaffold.from_rows(SOURCE, 'f', rows('0x58', '0x38', ('s', 'r'))) == []
    assert scaffold.from_rows(SOURCE.replace('s32 i;', 's32 frame_pad;'), 'f', rows('0x58', '0x38')) == []
