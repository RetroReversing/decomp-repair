import pytest

from decomprepair.masked_slot_dispatch import applies, rewrite, variants

SOURCE = '''
M2C_UNK invoke(s32, s32, s32, M2C_UNK);
extern M2C_UNK offsets;
extern M2C_UNK enables;
extern M2C_UNK state;
void visit(void *slots, s32 a, s32 b, M2C_UNK c, s32 mask) {
    s32 displacement;
    s32 i;
    s32 j;
    s32 stride;
    s32 value;
    i = 0;
    if ((s32) M2C_FIELD(slots, u16 *, 4) > 0) {
        j = 0;
        stride = 0;
        do {
            if ((*(j + ((M2C_FIELD(&state, u8 *, 16) * 0x22) + &offsets)) >= 0) &&
                (mask & *(&enables + (((M2C_FIELD(&state, u8 *, 16) * 0x11) + i) * 4)))) {
                switch (i) {
                case 3:
                case 5:
                    value = M2C_FIELD(&state, u16 *, 20) & 0x8000;
test:
                    if (value == 0) {
                    default:
                        displacement = *(j + ((M2C_FIELD(&state, u8 *, 16) * 0x22) + &offsets)) * 4;
                        invoke(M2C_FIELD(slots, s32 *, 0) + stride, a + displacement, b + displacement, c);
                    }
                    break;
                case 4:
                case 6:
                    value = M2C_FIELD(&state, u16 *, 20) & 0x4000;
                    goto test;
                case 10:
                    value = M2C_FIELD(&state, u16 *, 20) & 0x800;
                    goto test;
                case 11:
                    value = M2C_FIELD(&state, u16 *, 20) & 0x2000;
                    goto test;
                case 9:
                    value = M2C_FIELD(&state, u16 *, 20) & 0x1000;
                    goto test;
                }
            }
            j += 2;
            i += 1;
            stride += 0x24;
        } while (i < (s32) M2C_FIELD(slots, u16 *, 4));
    }
}
'''
ASM = '''
lhu $v0, 0x4($s3)
addiu $s4, $s4, %lo(offsets)
lui $fp, %hi(jtbl_80002000)
addiu $fp, $fp, %lo(jtbl_80002000)
lbu $v1, %lo(state + 16)($v1)
lh $v0, 0x0($v0)
lhu $v0, %lo(enables)($at)
addiu $v1, $s0, -0x3
sltiu $v0, $v1, 0x9
beqz $v0, .Ldefault
sll $v0, $v1, 2
addu $v0, $v0, $fp
lw $v0, 0x0($v0)
jr $v0
nop
.Lflag3:
lui $v0, %hi(state + 20)
lhu $v0, %lo(state + 20)($v0)
j .Ltest
andi $v0, $v0, 0x8000
.Lflag4:
lui $v0, %hi(state + 20)
lhu $v0, %lo(state + 20)($v0)
j .Ltest
andi $v0, $v0, 0x4000
.Lflag10:
lui $v0, %hi(state + 20)
lhu $v0, %lo(state + 20)($v0)
j .Ltest
andi $v0, $v0, 0x800
.Lflag11:
lui $v0, %hi(state + 20)
lhu $v0, %lo(state + 20)($v0)
j .Ltest
andi $v0, $v0, 0x2000
.Lflag9:
lui $v0, %hi(state + 20)
lhu $v0, %lo(state + 20)($v0)
andi $v0, $v0, 0x1000
.Ltest:
bnel $v0, $zero, .Ladvance
addiu $s1, $s1, 0x2
.Ldefault:
addu $a0, $a0, $s2
jal invoke
addu $a2, $s6, $a2
.Ladvance:
addiu $s2, $s2, 0x24
'''
CASES = ('.Lflag3', '.Lflag4', '.Lflag3', '.Lflag4', '.Ldefault', '.Ldefault', '.Lflag9', '.Lflag10', '.Lflag11')
DATA = 'dlabel jtbl_80002000\n' + ''.join(f'.word {label}\n' for label in CASES)


@pytest.mark.parametrize('extra', [False, True])
def test_typed_slot_dispatch_preserves_both_call_layouts(extra):
    src = SOURCE
    if extra:
        src = (src.replace('invoke(s32, s32, s32, M2C_UNK)', 'invoke(s32, s32, M2C_UNK, M2C_UNK, s32)')
                  .replace('s32 b, M2C_UNK c, s32 mask)', 'M2C_UNK b, M2C_UNK c, s32 mask, s32 out)')
                  .replace('a + displacement, b + displacement, c)', 'a + displacement, b, c, out + displacement)'))
    asm = ASM.replace('addu $a2, $s6, $a2', 'sw $v0, 0x10($sp)') if extra else ASM
    fixed = rewrite(src, 'visit', asm, DATA)
    assert applies(ASM)
    assert 'extern s16 offsets[][17];' in fixed
    assert ('[][17];' if extra else '[][2];') in fixed
    assert '__m2c_slot_stride = __m2c_slot_index * 36;' in fixed
    assert 's16 __m2c_slot_offset;' in fixed
    assert 'goto ' not in fixed
    assert ('out + __m2c_slot_offset' if extra else 'b + __m2c_slot_offset') in fixed


def test_slot_dispatch_requires_the_actual_case_destinations_and_flag_bits():
    assert not rewrite(SOURCE, 'visit', ASM, DATA.replace('.word .Ldefault', '.word .Lflag4', 1))
    assert not rewrite(SOURCE, 'visit', ASM.replace('0x8000', '0x10'), DATA)
    assert not rewrite(SOURCE, 'visit', ASM, DATA, 'extern u8 state[];')
    assert not rewrite(SOURCE, 'visit', ASM.replace('addu $a2, $s6, $a2', 'nop'), DATA)


def test_slot_dispatch_reads_exactly_nine_words_for_a_compiled_draft():
    labels = {label: 0x80000100 + index * 4 for index, label in enumerate(sorted(set(CASES)))}
    asm = ASM
    for label, addr in labels.items():
        asm = asm.replace(label + ':\n', f'{label}:\n/* 00 {addr:08X} 00000000 */ ')
    table = b''.join(labels[label].to_bytes(4, 'big') for label in CASES)

    def read(symbol, size):
        assert (symbol, size) == ('jtbl_80002000', 36)
        return table

    assert variants(SOURCE, 'visit', asm, '', read_data=read, big_endian=True)[0][0] == 'masked_slot_dispatch'
    assert not variants(SOURCE, 'visit', asm, '', read_data=read, big_endian=False)
