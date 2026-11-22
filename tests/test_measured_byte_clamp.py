from decomprepair.measured_byte_clamp import variants

SOURCE = '''
extern M2C_UNK table;
extern M2C_UNK state;
s32 f(s32 input) {
    s32 result;
    u32 index;
    u8 limit;
    u8 current;
    current = input;
    index = current & 0xFF;
    result = 0;
    if (index >= 2U) {
        limit = *(&table + 0x120 + M2C_FIELD(M2C_FIELD(&state, void **, 0x20), u16 *, 0x16));
        if (limit < index) { current = limit; }
        result = current & 0xFF;
    }
    return result;
}
'''
ROWS = [
    (' ', 'lhu $v0, 0x16($v0)', 'lhu $v0, 0x16($v0)'),
    ('>', '', 'sll $v0, $v0, 2'),
    ('i', 'lbu $v1, %lo(target)($v1)', 'lbu $v1, %lo(other)($v1)'),
]


def test_byte_base_and_early_return():
    [(family, candidate)] = variants(SOURCE, 'f', '', ROWS)
    assert family == 'measured_byte_clamp'
    assert '(s8 *)&table + 0x120' in candidate
    assert 'if (index < 2U) { return 0; }' in candidate
    assert 'return current & 0xFF;' in candidate


def test_requires_evidence_and_safe_local_scope():
    cases = [
        (SOURCE, '', []),
        (SOURCE.replace('s32 result;', 'volatile s32 result;'), '', ROWS),
        (SOURCE.replace('if (limit < index)', 'use(result); if (limit < index)'), '', ROWS),
        (SOURCE.replace('if (limit < index)', 'goto done; if (limit < index)'), '', ROWS),
        (SOURCE, 'extern int table;', ROWS),
        (SOURCE, '#define EXPOSE result', ROWS),
        (SOURCE.replace('u16 *', 's16 *'), '', ROWS),
    ]
    for source, header, rows in cases:
        assert variants(source, 'f', header, rows) == []
