from decomprepair import measured_field_base_lifetimes as repair

HEADER = 'typedef signed char s8; typedef unsigned char u8; typedef unsigned short u16;'
SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern void *current;
void f(void) {
    u8 mode;
    void *entry;
    void *record;
    mode = M2C_FIELD(current, u8 *, 4);
    entry = M2C_FIELD(record, void **, 8);
    if (mode == 0) {
        M2C_FIELD(current, u8 *, 10) = (u8) M2C_FIELD(entry, u8 *, 2);
        first(M2C_FIELD(entry, u8 *, 2), M2C_FIELD(current, u8 *, 10), current);
        M2C_FIELD(current, u8 *, 20) = (u8) M2C_FIELD(record, u16 *, 6);
        second(record, current);
    }
}
'''
ROWS = [
    ('r', 'lui $a2, %hi(current)', 'lui $a2, %hi(current)'),
    (' ', 'lw $a2, %lo(current)($a2)', 'lw $a2, %lo(current)($a2)'),
    (' ', 'sb $v0, 10($a2)', 'sb $v0, 10($a2)'),
    ('r', 'lui $v0, %hi(current)', 'lui $a2, %hi(current)'),
    ('r', 'lw $v0, %lo(current)($v0)', 'lw $a2, %lo(current)($a2)'),
    (' ', 'jal first', 'jal first'),
    (' ', 'lhu $v0, 6($a0)', 'lhu $v0, 6($a0)'),
    ('o', 'jal second', 'sb $v0, 20($a1)'),
    ('o', 'sb $v0, 20($a1)', 'lui $a1, %hi(current)'),
]


def test_independent_and_combined_pointer_lifetimes():
    variants = repair.variants(SOURCE, 'f', HEADER, ROWS)
    assert len(variants) == 3
    assert '__repair_firstbase = current;' in variants[0][1]
    assert '__repair_storebase = current;' in variants[1][1]
    combined = variants[2][1]
    assert 'M2C_FIELD(__repair_firstbase, u8 *, 10)' in combined
    assert 'second(record, __repair_storebase);' in combined


def test_no_proposals_without_evidence_or_with_hidden_writes():
    assert not repair.variants(SOURCE, 'f', HEADER, [])
    assert not repair.variants(SOURCE, 'f', HEADER + '\n#define current alternate', ROWS)
    out = repair.variants(SOURCE.replace('entry = M2C_FIELD', 'entry = evil(), M2C_FIELD'), 'f', HEADER, ROWS)
    assert out and all('__repair_firstbase' not in candidate for _, candidate in out)
    assert not repair.variants(SOURCE.replace('void f(void)', 'void f(void *current)'), 'f', HEADER, ROWS)
    assert not repair.variants(SOURCE, 'f', HEADER.replace('unsigned short', 'volatile short'), ROWS)
