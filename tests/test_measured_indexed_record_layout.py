from decomprepair.measured_indexed_record_layout import variants

SOURCE = '''extern M2C_UNK D_80001000;
extern M2C_UNK D_80001174;
extern M2C_UNK D_8000117C;
void update(s32 index) {
    s32 offset; void *seq; void *player;
    offset = index * 0x184;
    player = offset + &D_80001000;
    if (check(player) == 0) {
        seq = offset + (&D_80001000 + 0x7C);
        load(seq, *(&D_80001174 + offset));
        set(player, seq);
        play(player);
        return;
    }
    stop(player);
    *(&D_8000117C + offset) = *(&D_8000117C + offset) | 2;
}
'''
TARGET = ['sll $s1, $v0, 2', 'addiu $s0, $s0, 0x7c', 'lui $s0, %hi(D_80001000)',
          'lui $a1, %hi(D_80001174)', 'lui $v0, %hi(D_8000117C)',
          'jal check', 'jal load', 'jal set', 'jal play', 'jal stop']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         'sll $s1, $v0, 4' if i == 0 else 'nop') for i in range(40)]


def test_reconstructs_indexed_layout():
    result = variants(SOURCE, 'update', '', ROWS)
    assert len(result) == 1
    assert 'extern __repair_record D_80001000[];' in result[0][1]
    assert 'D_80001000[index].flags |= 2;' in result[0][1]


def test_rejects_inconsistent_addresses_and_evidence():
    assert not variants(SOURCE.replace('D_80001174', 'D_80001178'), 'update', '', ROWS)
    assert not variants(SOURCE, 'update', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE, 'update', 'extern int D_80001000;', ROWS)
    assert not variants(SOURCE.replace('offset = index', '/* note */ offset = index'), 'update', '', ROWS)
