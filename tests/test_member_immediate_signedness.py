from decomprepair.member_immediate_signedness import variants

ASM = 'addiu $a0, $zero, -0x1\nsh $a0, 0x5F4($v0)\n'
SOURCE = '''typedef struct { u16 a, b, c; f32 scale; u16 d; u8 e; } Fx;
void f(Fx *p) {
    p->a = -1;
    p->b = -1;
    p->c = 0;
    p->d = -1;
}
'''


def test_the_assigned_members_become_signed_together_in_declaration_order():
    family, text = variants(SOURCE, 'f', ASM)[0]
    assert family == 'member_immediate_signedness'
    assert 'typedef struct { s16 a; s16 b; u16 c; f32 scale; s16 d; u8 e; } Fx;' in text


def test_a_cast_store_becomes_signed():
    source = 'void f(char *p) {\n    *((u16 *) (p + 4)) = -1;\n}\n'
    assert '(s16 *)' in variants(source, 'f', ASM)[0][1]


def test_nothing_without_a_negative_immediate_in_the_target():
    assert variants(SOURCE, 'f', 'ori $a0, $zero, 0xffff\n') == []
    assert variants(SOURCE, 'f', '') == []
