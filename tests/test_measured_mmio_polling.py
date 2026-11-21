import pytest

from decomprepair import measured_mmio_polling

STATUS = '0xA4400020'
OUTPUT = '0xA5400040'
SOURCE = f'''
M2C_UNK resume(void *, M2C_UNK, void *); /* extern */
void poll(void) {{
    void *saved;
    void *ghost;
    saved = M2C_FIELD(&device, s32 *, 0x18) + 8;
    if (*(void *){STATUS} & 3) {{ do {{ }} while (*(void *){STATUS} & 3); }}
    *(void *){OUTPUT} = M2C_FIELD(saved, s32 *, 4) | 0x20000000;
    ghost = (void *)0xA4400000;
    if (*(void *){STATUS} & 3) {{
        ghost = (void *){STATUS};
        do {{ }} while (*(void *){STATUS} & 3);
    }}
    *(void *){OUTPUT} = M2C_FIELD(saved, s32 *, 4);
    resume(ghost, {OUTPUT}, saved);
    *(void *){STATUS} = 2;
    mask |= 16;
}}
'''


def polling_loop(label):
    return f'''andi $v0, $v1, 3
beqz $v0, .Lexit{label}
lui $a0, ({STATUS} >> 16)
ori $a0, $a0, ({STATUS} & 0xFFFF)
.Lloop{label}:
lw $v1, 0($a0)
andi $v0, $v1, 3
bnez $v0, .Lloop{label}
nop
.Lexit{label}:
'''


ASM = f'''lui $v0, %hi(device + 0x18)
lw $v0, %lo(device + 0x18)($v0)
lui $v1, ({STATUS} >> 16)
ori $v1, $v1, ({STATUS} & 0xFFFF)
sw $ra, 16($sp)
lw $v1, 0($v1)
addiu $a2, $v0, 8
{polling_loop(1)}lui $a1, ({OUTPUT} >> 16)
ori $a1, $a1, ({OUTPUT} & 0xFFFF)
lui $a0, ({STATUS} >> 16)
lw $v0, 4($a2)
ori $a0, $a0, ({STATUS} & 0xFFFF)
lui $v1, (0x20000000 >> 16)
or $v0, $v0, $v1
sw $v0, 0($a1)
lw $v1, 0($a0)
{polling_loop(2)}lw $v1, 4($a2)
lui $v0, ({OUTPUT} >> 16)
ori $v0, $v0, ({OUTPUT} & 0xFFFF)
jal resume
sw $v1, 0($v0)
lui $a1, ({STATUS} >> 16)
ori $a1, $a1, ({STATUS} & 0xFFFF)
addiu $v0, $zero, 2
sw $v0, 0($a1)
'''


def test_rewrite_stages_each_poll_and_preserves_order():
    candidate = measured_mmio_polling.rewrite(SOURCE, 'poll', ASM)

    assert measured_mmio_polling.applies(ASM)
    assert candidate.count(f'= *(volatile u32 *){STATUS};') == 4
    assert candidate.count('while (__m2c_poll_status & 3);') == 2
    assert 'void resume(void);' in candidate
    operations = [line.strip() for line in candidate.splitlines() if 'volatile u32' in line or 'resume();' in line]
    read = f'__m2c_poll_status = *(volatile u32 *){STATUS};'
    assert operations == [
        read, read,
        f'*(volatile u32 *){OUTPUT} = M2C_FIELD(saved, s32 *, 4) | 0x20000000;',
        read, read,
        f'*(volatile u32 *){OUTPUT} = (s32) M2C_FIELD(saved, s32 *, 4);',
        'resume();', f'*(volatile u32 *){STATUS} = 2;',
    ]


@pytest.mark.parametrize('asm', [
    ASM.replace('lw $v1, 0($v1)', 'lw $v1, 0($a1)'),
    ASM.replace('sw $v0, 0($a1)\nlw $v1, 0($a0)', 'sw $v0, 0($a1)\nlw $v1, 0($a1)'),
    ASM.replace('jal resume\nsw $v1, 0($v0)', 'jal resume\nnop'),
])
def test_rewrite_requires_matching_loads_and_delay_slot_store(asm):
    assert measured_mmio_polling.rewrite(SOURCE, 'poll', asm) is None


def test_rewrite_keeps_authored_prototype_and_unrecognized_arguments():
    assert measured_mmio_polling.rewrite(SOURCE, 'poll', ASM, 'int resume(int);') is None
    assert measured_mmio_polling.rewrite(SOURCE.replace('ghost,', 'saved,'), 'poll', ASM) is None
