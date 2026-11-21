"""KMC address inputs that match when a generated pointer uses byte units."""

from decomprepair import measured_storage_shapes


def _proposals(source, target, candidate):
    rows = [('i' if a != b else ' ', a, b) for a, b in zip(target, candidate, strict=True)]
    return measured_storage_shapes.variants(source, 'update', '', rows, 'MIPS', big_endian=True)


def test_relocated_word_addresses_require_all_matching_loads_and_stores():
    source = '''extern M2C_UNK table;
extern M2C_UNK result;
extern M2C_UNK fallback;
void update(s32 i) {
    s32 value;
    value = *(&table + ((i + 1) * 4));
    *(&result + (i * 16)) = value;
    *(&result + ((i + 1) * 16)) = &fallback;
}
'''
    target = [
        'sll $v0, $v0, 2', 'lui $v1, %hi(table)', 'addu $v1, $v1, $v0', 'lw $v1, %lo(table)($v1)',
        'sll $v0, $v0, 4', 'lui $at, %hi(result)', 'addu $at, $at, $v0', 'sw $v1, %lo(result)($at)',
        'sll $v1, $v1, 4', 'lui $v0, %hi(fallback)', 'addiu $v0, $v0, %lo(fallback)',
        'lui $at, %hi(result)', 'addu $at, $at, $v1', 'j .Lexit', 'sw $v0, %lo(result)($at)',
    ]
    candidate = list(target)
    for i, bad in ((0, 'sll $v0, $v0, 4'), (4, 'sll $v0, $v0, 6'), (8, 'sll $v1, $v1, 6')):
        candidate[i] = bad
    [(family, fixed)] = _proposals(source, target, candidate)
    assert family == 'relocated_word_array_offsets'
    assert 'value = *(u32 *)((u8 *)&table + ((i + 1) * 4));' in fixed
    assert '*(u32 *)((u8 *)&result + ((i + 1) * 16)) = (u32)&fallback;' in fixed
    assert not _proposals(source.replace('*(&result + (i * 16)) = value;', ''), target, candidate)
    assert not _proposals(source, target, [*candidate[:8], 'sll $v1, $v1, 5', *candidate[9:]])


def test_shifted_bytes_need_both_reassociation_and_a_byte_base():
    source = '''extern M2C_UNK origin;
extern u8 column;
extern u8 row;
void update(void *record) {
    M2C_FIELD(record, void **, 12) = (void *) ((column << 4) + ((row << 7) + &origin));
}'''
    target = [
        'lui $a1, %hi(column)', 'lbu $a1, %lo(column)($a1)', 'sll $a1, $a1, 4',
        'lui $v0, %hi(row)', 'lbu $v0, %lo(row)($v0)', 'sll $v0, $v0, 7',
        'lui $v1, %hi(origin)', 'addiu $v1, $v1, %lo(origin)', 'addu $v0, $v0, $v1',
        'addu $a1, $a1, $v0', 'sw $a1, 12($a2)',
    ]
    candidate = [
        'lui $a1, %hi(row)', 'lbu $a1, %lo(row)($a1)', 'sll $a1, $a1, 9',
        'lui $v0, %hi(column)', 'lbu $v0, %lo(column)($v0)', 'sll $v0, $v0, 6', *target[6:],
    ]
    [(family, fixed)] = _proposals(source, target, candidate)
    assert family == 'relocated_two_byte_sum'
    assert '(row << 7) + ((column << 4) + (u8 *)&origin)' in fixed
    assert not _proposals(source.replace('void **, 12', 'void **, 16'), target, candidate)
    assert not _proposals(source, target, [*candidate[:5], 'sll $v0, $v0, 7', *candidate[6:]])
