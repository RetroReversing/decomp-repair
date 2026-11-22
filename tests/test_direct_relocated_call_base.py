from decomprepair.direct_relocated_call_base import variants

HEADER = 'extern char assetBase[];'
SOURCE = '''
void copy(s32 destination, s32 length) {
    char *base = assetBase;
    s32 offset;
    offset = length * 12;
    transfer(destination, (s32)(base + offset), length);
}
'''
ROWS = [
    ('r', 'lui $a1, %hi(assetBase)', 'lui $t0, %hi(assetBase)'),
    ('r', 'addiu $a1, $a1, %lo(assetBase)', 'addiu $t0, $t0, %lo(assetBase)'),
    (' ', 'sll $a2, $s0, 2', 'sll $a2, $s0, 2'),
    (' ', 'jal transfer', 'jal transfer'),
    ('r', 'addu $a1, $v1, $a1', 'addu $a1, $t0, $v1'),
]


def test_use_relocated_char_array_in_measured_argument_slot():
    [(label, candidate)] = variants(SOURCE, 'copy', HEADER, ROWS)
    assert label == 'direct_relocated_call_base'
    assert 'transfer(destination, (s32)(offset + assetBase), length);' in candidate


def test_reject_written_alias_macro_and_unrelated_disassembly():
    mutable = SOURCE.replace('offset = length * 12;', 'offset = length * 12; base += 8;')
    shadow = SOURCE.replace('offset = length * 12;', 'offset = length * 12; { char *assetBase;')
    assert not variants(mutable, 'copy', HEADER, ROWS)
    assert not variants(shadow, 'copy', HEADER, ROWS)
    assert not variants(SOURCE, 'copy', HEADER + '\n#define transfer copy_data', ROWS)
    assert not variants(SOURCE, 'copy', HEADER, ROWS[:-1])
