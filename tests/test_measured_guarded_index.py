from decomprepair.measured_guarded_index import variants

SOURCE = '''void walk(void *list) {
    s32 count;
    void *cursor;
    count = M2C_FIELD(list, s32 *, 0x7C);
    if (count >= 2) {
        cursor = (count * 4) + list;
        use(cursor);
    }
}
'''
TARGET = ['slti $v0, $s1, 2', 'xori $v0, $v0, 1', 'beqz $v0, 0x78', 'move $s2, $zero',
          'sll $v0, $s1, 2', 'addu $s0, $v0, $a0']
CANDIDATE = ['slti $v0, $s1, 2', 'bnez $v0, 0x74', 'move $s2, $zero',
             'sll $v0, $s1, 2', 'addu $s0, $a0, $v0']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(30)]


def test_explicit_guard_and_indexed_address():
    result = variants(SOURCE, 'walk', '', ROWS)
    assert len(result) == 1
    assert '__repair_guard = (count < 2) ^ 1;' in result[0][1]
    assert '(void *) ((u32) (count * 4) + (u32) list)' in result[0][1]


def test_requires_target_and_matching_source():
    assert not variants(SOURCE, 'walk', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('count * 4', 'count * 8'), 'walk', '', ROWS)
    assert not variants(SOURCE.replace('s32 count', 'volatile s32 count'), 'walk', '', ROWS)
    assert not variants(SOURCE.replace('cursor =', '/* keep */ cursor ='), 'walk', '', ROWS)
