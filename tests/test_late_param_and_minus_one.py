from decomprepair import float_argument_prototype, late_param_narrow, unsigned_minus_one

SOURCE = '''void g(s32, s32, s32, s32);
void f(s32 *gp, s32 x, s32 y, s32 step, s32 a4)
{
    u16 px;
    px = x;
    g(px, y, a4, step);
    px = step + px;
}
'''
ASM = '''addiu      $sp, $sp, -0x20
sw         $ra, 0x1C($sp)
lw         $s2, 0x30($sp)
addu       $s5, $a3, $zero
jal        g
'''


def test_the_late_copy_narrows_the_parameter_with_its_accumulator():
    children = [text for _, text in late_param_narrow.variants(SOURCE, 'f', asm=ASM)]
    assert SOURCE.replace('s32 step', 'u16 step') in children  # (the local is already narrow)
    wide = SOURCE.replace('u16 px;', 's32 px;')
    first = late_param_narrow.variants(wide, 'f', asm=ASM)[0][1]
    assert 'u16 step' in first and 'u16 px;' in first
    early = ASM.replace('lw         $s2, 0x30($sp)\n', '')
    assert late_param_narrow.variants(SOURCE, 'f', asm=early) == []


def test_minus_one_fields_turn_unsigned_together():
    source = '''typedef struct { u16 id; s16 prev; s16 next; } N;
extern N D[];
void f(void)
{
    D[0].prev = -1;
    D[1].next = -1;
}
'''
    asm = 'ori        $a0, $zero, 0xFFFF\n'
    first = unsigned_minus_one.variants(source, 'f', asm=asm)[0][1]
    assert 'u16 prev; u16 next;' in first
    assert unsigned_minus_one.variants(source, 'f', asm='addiu $a0, $zero, -1\n') == []


def test_a_copied_zero_argument_is_a_float():
    source = '''void g(s32, s32, s32, s32);
void f(void)
{
    g(0x41, 0, 0, 0);
}
'''
    asm = '''addiu      $a0, $zero, 0x41
addu       $a1, $zero, $zero
addu       $a2, $a1, $zero
jal        g
 addu      $a3, $zero, $zero
'''
    children = [text for _, text in float_argument_prototype.variants(source, 'f', asm=asm, flags=['-O1'])]
    assert source.replace('void g(s32, s32, s32, s32);', 'void g(s32, f32, f32, s32);').replace(
        'g(0x41, 0, 0, 0)', 'g(0x41, 0.0f, 0.0f, 0)') in children
    plain = asm.replace('addu       $a2, $a1, $zero', 'addu       $a2, $zero, $zero')
    assert float_argument_prototype.variants(source, 'f', asm=plain, flags=['-O1']) == []
