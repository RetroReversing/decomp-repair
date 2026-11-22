from decomprepair.measured_byte_loop_key import variants

SOURCE = '''extern char key[];
extern s32 state;
void scan(s32 count) {
    s32 offset;
    s32 i;
    offset = 0;
    if (count > 0) {
        offset = 0;
        do {
            if (*(s32 *)(offset + M2C_FIELD(&state, s32 *, 16)) == key) consume(i);
            offset += 20;
            i += 1;
        } while (i < count);
    }
}'''
T = ['lui $s4, %hi(key)', 'addiu $s4, $s4, %lo(key)', 'move $s1, $zero',
     'lui $v0, %hi(table)', 'lw $v0, %lo(table)($v0)', 'addu $v0, $s1, $v0',
     'lbu $v0, ($v0)', 'bnel $v0, $s4, 100']
C = ['move $s1, $zero', 'lui $s4, %hi(key)', 'addiu $s4, $s4, %lo(key)',
     'lui $v0, %hi(table)', 'lw $v0, %lo(table)($v0)', 'addu $v0, $s1, $v0',
     'lw $v0, ($v0)', 'bnel $v0, $s4, 100']
ROWS = [('r', a, b) for a, b in zip(T, C)]
SYMBOLS = {'state': 100, 'table': 116}


def test_stages_key_and_reads_byte():
    # The loop index is initialized once before its use.
    source = SOURCE.replace('    offset = 0;\n    if', '    if')
    label, fixed = variants(source, 'scan', '', ROWS, ['-mgp32'], SYMBOLS.get)[0]
    assert label == 'measured_byte_loop_key'
    assert '__repair_loop_key = (s32) key;' in fixed
    assert '*(u8 *)(offset + M2C_FIELD(&state, s32 *, 16)) == __repair_loop_key' in fixed
    assert fixed.index('__repair_loop_key =') < fixed.index('offset = 0;')


def test_requires_symbol_resolution_word_abi_and_unique_loop():
    source = SOURCE.replace('    offset = 0;\n    if', '    if')
    assert not variants(source, 'scan', '', ROWS, ['-mgp64'], SYMBOLS.get)
    assert not variants(source, 'scan', '', ROWS, ['-mgp32'], {'state': 100, 'table': 120}.get)
    assert not variants(SOURCE, 'scan', '', ROWS, ['-mgp32'], SYMBOLS.get)
    assert not variants(source, 'scan', '#define offset shared', ROWS, ['-mgp32'], SYMBOLS.get)
    assert not variants(source, 'scan', '', [(' ', x, x) for x in T], ['-mgp32'], SYMBOLS.get)
