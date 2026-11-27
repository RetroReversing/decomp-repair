from decomprepair.param_cursor_each import FAMILY, variants

SOURCE = '''extern char D_80001000[];
extern char D_80002000[];

void draw(void **arg0, s32 arg1) {
    f32 temp_f;
    s32 var_v0;
    void *temp_v1;
    void *temp_v1_2;

    temp_v1 = *arg0;
    *arg0 = temp_v1 + 8;
    M2C_FIELD(temp_v1, s32 *, 0) = 0xE7000000;
    M2C_FIELD(temp_v1, s32 *, 4) = 0;
    temp_v1_2 = *arg0;
    *arg0 = temp_v1_2 + 8;
    M2C_FIELD(temp_v1_2, s32 *, 0) = 0xFD100000;
    temp_f = *(D_80001000 + (arg1 * 4));
    if (temp_f >= 2.1474836e9f) {
        var_v0 = ((s32) (temp_f - 2.1474836e9f) | 0x80000000) & 0xFFFF;
    } else {
        var_v0 = (s32) temp_f & 0xFFFF;
    }
    M2C_FIELD(temp_v1_2, s32 *, 4) = (s32) *(D_80002000 + var_v0);
}
'''
ASM = '''lbu $v0, %lo(D_80002000)($at)
lwc1 $f0, %lo(D_80001000)($at)
'''


def test_each_command_keeps_its_own_write_back_and_values_move_into_the_word():
    children = variants(SOURCE, 'draw', '', ASM)
    assert children and all(family == FAMILY for family, _ in children)
    text = next(t for _, t in children if '(u16) (u32)' in t and 'extern u8 D_80002000[];' in t)
    body = text[text.index('void draw'):]
    assert body.count('((*(ParamCommand **)arg0)++)') == 2
    assert 'cmd->w0 = 0xFD100000; cmd->w1 = ' in body
    assert '(u16) (u32) (' in body
    for gone in ('temp_f', 'var_v0', 'temp_v1', '2.1474836e9f'):
        assert gone not in body


def test_a_local_read_after_its_command_stays_unwritten():
    source = SOURCE.replace('    M2C_FIELD(temp_v1_2, s32 *, 4) = (s32) *(D_80002000 + var_v0);\n',
                            '    M2C_FIELD(temp_v1_2, s32 *, 4) = (s32) *(D_80002000 + var_v0);\n    use(var_v0);\n')
    assert variants(source, 'draw', '', ASM) == []


def test_nothing_without_a_cursor_passed_by_address():
    assert variants('void f(s32 a) { M2C_FIELD(a, s32 *, 0) = 1; }\n', 'f') == []
