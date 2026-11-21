from decomprepair.stack_word_index_drafts import applies, rewrite

SLOTS = tuple(range(0, 32, 4))
LOCALS = '\n'.join(f'    s32 sp{offset:X};' for offset in SLOTS)
COPIES = '\n'.join(f'    sp{offset:X} = M2C_FIELD(&table, s32 *, {offset});' for offset in SLOTS)
SOURCE = f'''
extern M2C_UNK table;
s32 f(u32 input) {{
{LOCALS}
    s32 i;
    s32 result;
    u32 divisor;
    u32 digit;
    u32 value;

    value = input;
{COPIES}
    result = 0;
    if (value <= 99U) {{
        digit = 0x10;
        i = 0;
        do {{
            divisor = *((i * 4) + sp);
            result |= (value / divisor) * digit;
            value = value % divisor;
            i += 1;
            digit = digit >> 4;
        }} while (i < 8);
        return result;
    }}
    return 0x11223344;
}}
'''

MOVES = []
for offsets in (SLOTS[:3], SLOTS[3:6], SLOTS[6:]):
    values = list(zip(('$v0', '$v1', '$a0'), offsets))
    MOVES += [f'lw {reg}, {off}($a1)' for reg, off in values]
    MOVES += [f'sw {reg}, {off}($sp)' for reg, off in values]
ASM = '''
addiu $sp, $sp, -32
lui $a1, %hi(table)
addiu $a1, $a1, %lo(table)
''' + '\n'.join(MOVES) + '''
sll $v0, $a0, 2
addu $v0, $v0, $sp
lw $v0, 0($v0)
divu $zero, $a2, $v0
slti $v0, $a0, 8
j .Lend
move $v0, $a3
.Lfallback:
lui $a3, (0x11223344 >> 16)
ori $a3, $a3, (0x11223344 & 0xFFFF)
move $v0, $a3
.Lend:
jr $ra
addiu $sp, $sp, 32
'''


def test_restore_grouped_words_and_share_the_result_register():
    assert applies(ASM)
    fixed = rewrite(SOURCE, 'f', ASM)
    assert 'u32 words[8]' in fixed
    assert '__repair_indexed_words = table;' in fixed
    assert 'divisor = __repair_indexed_words.words[i];' in fixed
    assert '} else {\n        result = 0x11223344;\n    }\n    return result;' in fixed
    assert 'sp1C' not in fixed
    assert not applies(ASM.replace('sw $v1, 28($sp)', 'sw $v1, 24($sp)'))
    assert not applies(ASM.replace('divu $zero, $a2, $v0', 'divu $zero, $a2, $v1'))
    assert not rewrite(SOURCE.replace('0x11223344', '0x11223345'), 'f', ASM)
    assert not rewrite(SOURCE, 'f', ASM, 'extern u32 table[8];')
