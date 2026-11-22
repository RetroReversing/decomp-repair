from decomprepair import measured_kmc_unsigned_indexed_byte as repair

SOURCE = '''extern char flags[];
int f(int i) {
    return *(flags + i) | 0xC800;
}'''
ROWS = [('|', 'lbu $v0, %lo(flags)($v0)', 'lb $v0, %lo(flags)($v0)')]


def test_unsigned_read_and_existing_arity_hypothesis(monkeypatch):
    monkeypatch.setattr(repair.target_call_arity_repairs, 'variants',
                        lambda text, name, asm: [('arity', text.replace('return', 'return /* arity */'))])
    result = repair.variants(SOURCE, 'f', '', ROWS, 'asm')
    assert len(result) == 2
    assert '(u8) *(flags + i)' in result[0][1]
    assert '/* arity */' in result[1][1]


def test_requires_matching_target_and_simple_read():
    assert not repair.variants(SOURCE, 'f', '', [], '')
    assert not repair.variants(SOURCE, 'f', '', [('|', 'lbu $v0, %lo(other)($v0)', ROWS[0][2])], '')
    assert not repair.variants(SOURCE.replace('flags + i', 'flags + i++'), 'f', '', ROWS, '')
    assert not repair.variants(SOURCE.replace('extern char', 'extern volatile char'), 'f', '', ROWS, '')
    assert not repair.variants(SOURCE.replace('| 0xC800', '+ 0xC800'), 'f', '', ROWS, '')
