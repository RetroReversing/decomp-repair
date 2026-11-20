from decomprepair.unaligned_stack_drafts import rewrite, stack_copy

ASM = """
glabel f
addiu $sp, $sp, -0x10
.Lloop:
lwl $v0, 0($t0)
lwr $v0, 3($t0)
lwl $v1, 4($t0)
lwr $v1, 7($t0)
swl $v0, 0($sp)
swr $v0, 3($sp)
swl $v1, 4($sp)
swr $v1, 7($sp)
lbu $v0, 2($sp)
lhu $v0, 4($sp)
lbu $v0, 6($sp)
lbu $v0, 7($sp)
addiu $t0, $t0, 8
addiu $sp, $sp, 0x10
jr $ra
nop
"""

SOURCE = """
extern M2C_UNK items;
extern u8 count;
void f(u16 *arg) {
    M2C_UNK sp0;
    u16 sp4;
    s32 index;
    u16 *result;
    u32 state;
    void *bytes;
    M2C_UNK *row;
    result = arg;
    row = &items;
    index = 0;
    if ((s32) count > 0) {
        bytes = arg + 3;
        do {
            sp0 = M2C_UNALIGNED32(M2C_FIELD(row, M2C_UNK *, 0));
            sp4 = M2C_UNALIGNED32(M2C_FIELD(row, M2C_UNK *, 4));
            state = (u32) (sp2 & 0x30) >> 2;
            M2C_FIELD(bytes, s8 *, 1) = (s8) state;
            if (state == 0) {
                *result = sp4;
                M2C_FIELD(bytes, u8 *, -1) = sp6;
                M2C_FIELD(bytes, u8 *, 0) = sp7;
            }
            index += 1;
            row += 8;
            bytes += 6;
            result += 6;
        } while (index < (s32) count);
    }
}
"""


def test_covered_stack_views_share_the_copied_record():
    assert stack_copy(ASM) == (0, '$t0')
    result = rewrite(SOURCE, 'f', ASM)
    assert 'void f(u16 *arg)' in result
    assert '__m2c_unaligned_row = *(struct __m2c_unaligned_input *)__m2c_unaligned_src;' in result
    assert '->__m2c_unaligned_byte4 = (__m2c_unaligned_row.__m2c_unaligned_byte2 & 0x30) >> 2;' in result
    assert '->__m2c_unaligned_half0 = __m2c_unaligned_row.__m2c_unaligned_half4;' in result
    assert '__m2c_unaligned_index < count;' in result
    assert 'sp2' not in result and 'M2C_UNALIGNED32' not in result


def test_requires_the_copy_values_to_reach_the_same_stack_slots():
    assert not rewrite(SOURCE, 'f', ASM.replace('swr $v1, 7', 'swr $v0, 7'))
    assert not rewrite(SOURCE, 'f', ASM.replace('lbu $v0, 6($sp)', 'lh $v0, 6($sp)'))
    assert not rewrite(SOURCE, 'f', ASM.replace('lwr $v0, 3', 'lwr $v0, 2'))
    assert not rewrite(SOURCE, 'f', ASM.replace('addiu $t0, $t0, 8', 'addiu $t0, $t0, 4'))
    assert not rewrite(SOURCE.replace('= sp7;', '= sp9;'), 'f', ASM)
    assert not rewrite(SOURCE.replace('result += 6;', 'touch(); result += 6;'), 'f', ASM)


def test_absolute_counter_alias_needs_two_relocations_and_the_same_address():
    source = SOURCE.replace('count >', 'M2C_FIELD(&items, u8 *, 30) >').replace(
        '(s32) count);', '(s32) M2C_FIELD(&items, u8 *, 30));')
    load = 'lbu $v0, %lo(items + 0x1e)($v0)\n'
    asm = ASM + load * 2
    resolve = {'items': 0x80000000, 'D_8000001E': 0x8000001E}.get
    assert 'extern u8 D_8000001E;' in rewrite(source, 'f', asm, resolve=resolve)
    assert '__m2c_unaligned_index < M2C_FIELD(&items, u8 *, 30)' in rewrite(source, 'f', ASM + load, resolve=resolve)
    assert '__m2c_unaligned_index < M2C_FIELD(&items, u8 *, 30)' in rewrite(
        source, 'f', asm, 'extern float D_8000001E;', resolve=resolve)


def test_rewrite_keeps_argument_and_bound_names_out_of_generated_locals():
    source = SOURCE.replace('arg', 'output').replace('count', 'input')
    result = rewrite(source, 'f', ASM)
    assert 'void f(u16 *output)' in result
    assert '__m2c_unaligned_index < input;' in result
    assert rewrite(source, 'f', ASM, '#define __m2c_unaligned_index 3') is None
