

def test_shared_search_sentinel_with_truncated_byte_guard():
    from decomprepair.search_exit_loop_repairs import sentinel_byte_guard_variants

    source = """void f(s32 key) {
    u32 index;
    index = 0;
    do {
        if (matches(index, key)) {
            key = index;
            goto found;
        }
        ++index;
    } while (index < 4U);
    key = index;
    index = -1U;
found:
    if (key != -1) {
        if ((u8)(*(u8 *)((u8 *)&levels + (key * 0x10)) << 1) == 4) hit(key);
    }
}
"""
    rows = [
        ('<', 'addiu $a0, $zero, -1', ''),
        (' ', 'move $s0, $a0', 'move $s0, $a0'),
        (' ', 'lbu $v0, 8($s0)', 'lbu $v0, 8($s0)'),
        ('i', 'addiu $v1, $zero, 2', 'addiu $v1, $zero, 4'),
        ('>', '', 'sll $v0, $v0, 1'),
        (' ', 'andi $v0, $v0, 0xff', 'andi $v0, $v0, 0xff'),
    ]
    [(family, candidate)] = sentinel_byte_guard_variants(source, 'f', rows)
    assert family == 'search_sentinel_byte_guard'
    assert candidate.count('key = index;') == 1
    assert 'index = -1U;\nfound:\n    key = index;' in candidate
    assert '*(u8 *)((u8 *)&levels + (key * 0x10)) & 0x7f) == 2' in candidate
    assert not sentinel_byte_guard_variants(source, 'f', rows[1:])
    assert not sentinel_byte_guard_variants(source, 'f', rows[:-1])
    assert not sentinel_byte_guard_variants(source.replace('found:', 'goto found;\nfound:'), 'f', rows)
    assert not sentinel_byte_guard_variants(source.replace('matches(index, key)', 'matches(index, &key)'), 'f', rows)
