from decomprepair import measured_varbyte_lookup as repair

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
M2C_UNK apply(s32); /* extern */
void *f(void *dst, void *src) {
    u8 index;
    void *cursor;
    cursor = (void *)(src); cursor = (void *)((char *)cursor + (s32)(1));
    index = M2C_FIELD(src, u8 *, 0);
    if (index & 0x80) {
        index = ((index & 0x7F) << 8) | M2C_FIELD(src, u8 *, 1);
        cursor += 1;
    }
    apply(M2C_FIELD(M2C_FIELD(dst, void **, 0x70), s32 *, 0x10) + (index * 7));
    return cursor;
}
'''
ROWS = [
    ('r', 'lbu $v1, ($s0)', 'lbu $v1, ($a1)'),
    ('<', 'andi $v1, $v1, 0x7f', ''),
    ('i', 'lbu $v0, ($s0)', 'lbu $v1, 1($a1)'),
    ('<', 'sll $v1, $v1, 8', ''),
    ('<', 'or $v1, $v1, $v0', ''),
    (' ', 'jal apply', 'jal apply'),
]


def test_stage_full_width_index_and_compose_forwarding(monkeypatch):
    monkeypatch.setattr(repair.passthrough_argument_repairs, 'variants',
                        lambda src, name, **kwargs: [('passthrough_argument', src + '\n/* forwarded */')])
    result = dict(repair.variants(SOURCE, 'f', '', ROWS, ''))
    assert set(result) == {'measured_varbyte_lookup', 'forwarded_varbyte_lookup'}
    assert 'u32 index;' in result['measured_varbyte_lookup']
    assert 'index |= *cursor;' in result['measured_varbyte_lookup']
    assert result['forwarded_varbyte_lookup'].endswith('/* forwarded */')


def test_decline_changed_or_unproven_shapes(monkeypatch):
    monkeypatch.setattr(repair.passthrough_argument_repairs, 'variants', lambda *args, **kwargs: [])
    for source, header, rows in [
        (SOURCE, '', []),
        (SOURCE.replace('u8 index;', 'volatile u8 index;'), '', ROWS),
        (SOURCE.replace('cursor += 1;', 'cursor += 2;'), '', ROWS),
        (SOURCE.replace('return cursor;', 'use(index); return cursor;'), '', ROWS),
        (SOURCE, '#define index other()', ROWS),
        (SOURCE, '#undef M2C_FIELD', ROWS),
        (SOURCE, 'typedef volatile int u32;', ROWS),
        (SOURCE.replace('(*(type_ptr)', '(effect(), *(type_ptr)'), '', ROWS),
    ]:
        assert repair.variants(source, 'f', header, rows, '') == []
