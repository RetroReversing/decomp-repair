"""m2c's draft made to declare the table reads and stack slots it uses (m2c_undeclared_drafts.py)."""
from decomprepair.m2c_undeclared_drafts import rewrite, stack_frame, table_reads

TABLE = """s32 f(s32 a) {
    s32 t;
    t = *((a * 4) + &jtbl_80000A18);
    g(*(((s8) M2C_FIELD(&D_80012340, u8 *, 0) * 4) + &jtbl_80000A18));
    return t;
}
"""


def test_a_table_read_becomes_a_declared_word_index():
    out = table_reads(TABLE, 'f')
    assert out.startswith('extern s32 jtbl_80000A18[];\ns32 f(s32 a) {')
    assert 't = ((s32 *)jtbl_80000A18)[a];' in out
    assert 'g(((s32 *)jtbl_80000A18)[(s8) M2C_FIELD(&D_80012340, u8 *, 0)]);' in out
    assert '&jtbl' not in out.replace('jtbl_80000A18[]', '')


def test_a_table_read_of_another_shape_is_left_alone():
    source = 's32 f(s32 a) {\n    return *(a + &jtbl_80000A18);\n}\n'
    assert table_reads(source, 'f') == source


STACK = """void f(f32 *arg0) {
    f32 sp10;
    M2C_UNK sp68;
    f32 *var_a2;

    var_a2 = &sp10;
    sp14 = arg0[0];
    sp68 = *(f32 *)(sp + 8);
    if (sp != NULL) {
        var_a2 = &sp10[0];
    }
}
"""


def test_the_frame_is_one_array_and_each_slot_names_its_bytes():
    out = stack_frame(STACK, 'f', 'addiu $sp, $sp, -0x70')
    assert '    u8 sp[112];\n' in out
    assert '#define sp10 ((f32 *)(sp + 0x10))\n' in out  # used as an array too
    assert '#define sp14 (*(s32 *)(sp + 0x14))\n' in out  # never declared
    assert '#define sp68 (*(s32 *)(sp + 0x68))\n' in out  # M2C_UNK is not a type in a compiled draft
    assert 'f32 sp10;' not in out and 'M2C_UNK sp68;' not in out
    assert out.index('#define sp10') < out.index('void f(')


def test_the_frame_size_falls_back_to_the_last_slot():
    assert '    u8 sp[24];\n' in stack_frame('void f(void) {\n    sp10 = 1;\n}\n', 'f')


def test_a_draft_with_every_slot_declared_is_unchanged():
    source = 'void f(void) {\n    s32 sp10;\n\n    sp10 = 1;\n}\n'
    assert stack_frame(source, 'f') == source and rewrite(source, 'f') is None


def test_rewrite_is_idempotent():
    once = rewrite(STACK + TABLE, 'f', 'addiu $sp, $sp, -0x70')
    assert once and rewrite(once, 'f', 'addiu $sp, $sp, -0x70') is None
