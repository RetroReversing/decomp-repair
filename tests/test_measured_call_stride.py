"""A measured scale can need two assignments to allocate its call register."""

from decomprepair import measured_storage_shapes

SOURCE = '''void update(void) {
    if (M2C_FIELD(&state, u8 *, 16) != 255) {
        M2C_FIELD(&state, f32 *, 32) = M2C_FIELD(&state, f32 *, 28) * 8.0f;
        start(M2C_FIELD(&state, s32 *, 40) + (M2C_FIELD(&state, u8 *, 16) * 12), M2C_FIELD(&state, u8 *, 16));
        finish(M2C_FIELD(&state, s32 *, 40) + (M2C_FIELD(&state, u8 *, 16) * 12), 0);
    }
}
'''
TARGET = [
    'lbu $a1, ($s0)', 'beq $v1, $v0, 0x68',
    'sll $a0, $a1, 1', 'lui $at, %hi(input)', 'lwc1 $f2, %lo(input)($at)',
    'lui $at, 0x4100', 'mtc1 $at, $f0', 'nop', 'mul.s $f2, $f2, $f0',
    'lui $v0, %hi(base)', 'lw $v0, %lo(base)($v0)', 'addu $a0, $a0, $a1', 'sll $a0, $a0, 2',
    'lui $at, %hi(output)', 'swc1 $f2, %lo(output)($at)', 'jal start', 'addu $a0, $v0, $a0',
    'lbu $v0, ($s0)', 'jal finish', 'nop', 'jr $ra', 'nop',
]
ACTUAL = {2: 'sll $v0, $a1, 1', 9: 'lui $a0, %hi(base)', 10: 'lw $a0, %lo(base)($a0)',
          11: 'addu $v0, $v0, $a1', 12: 'sll $v0, $v0, 2', 16: 'addu $a0, $a0, $v0'}


def _proposals(source=SOURCE, actual=ACTUAL):
    rows = [('r', op, actual[i]) if i in actual else (' ', op, op) for i, op in enumerate(TARGET)]
    return measured_storage_shapes.variants(source, 'update', '', rows, '', big_endian=True)


def test_stages_only_the_first_calls_stride():
    [(family, candidate)] = _proposals()
    assert family == 'staged_call_stride'
    assert 's32 __repair_stride_index = M2C_FIELD(&state, u8 *, 16);' in candidate
    assert '__repair_stride_offset = (__repair_stride_index << 1) + __repair_stride_index;' in candidate
    assert '__repair_stride_offset = __repair_stride_offset << 2;' in candidate
    assert 'start(M2C_FIELD(&state, s32 *, 40) + __repair_stride_offset, ' in candidate
    assert next(line for line in SOURCE.splitlines() if 'finish(' in line) in candidate


def test_requires_observed_register_exchange_and_matching_scales():
    assert not _proposals(actual={**ACTUAL, 16: 'addu $a0, $a0, $v1'})
    assert not _proposals(SOURCE.replace('* 12', '* 20'))
    assert not _proposals(SOURCE.replace('finish(M2C_FIELD(&state, s32 *, 40)', 'finish(M2C_FIELD(&state, s32 *, 44)'))
