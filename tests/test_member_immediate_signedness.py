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


def test_signed_members_that_take_a_positive_top_bit_literal_become_unsigned():
    source = ('typedef struct { s8 tint; s8 other; s16 timer; } Rec;\nvoid f(void *p) {\n'
              '    (((Rec *) p)->tint) = 0xFF;\n    (((Rec *) p)->other) = 1;\n    (((Rec *) p)->timer) = 0xFFFF;\n}\n')
    asm = 'addiu $v0, $zero, 0xFF\nori $v0, $zero, 0xFFFF\n'
    family, text = variants(source, 'f', asm)[0]
    assert family == 'member_immediate_signedness'
    assert 'typedef struct { u8 tint; s8 other; u16 timer; } Rec;' in text
    assert variants(source, 'f', 'addiu $v0, $zero, -0x1\n') == []
