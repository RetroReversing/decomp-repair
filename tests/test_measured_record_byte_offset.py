from decomprepair.measured_record_byte_offset import variants

SOURCE = '''extern M2C_UNK base;
extern M2C_UNK result;
void setup(void *object, s32 size, s32 index) {
    s32 offset;
    M2C_FIELD(object, M2C_UNK **, 0xC) = &heap;
    offset = index * 0x184;
    *(&result + offset) = alloc(0, 0, &heap, 1, size);
    initialize(offset + &base, object);
}
'''
TARGET = ['sll $v1, $s0, 1', 'addu $v1, $v1, $s0', 'sll $v1, $v1, 5',
          'addu $v1, $v1, $s0', 'sll $v1, $v1, 2', 'lui $a0, %hi(base)',
          'addiu $a0, $a0, %lo(base)', 'addu $a0, $v1, $a0', 'lui $at, %hi(result)',
          'addu $at, $at, $v1', 'sw $v0, %lo(result)($at)']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         'sll $s0, $s0, 4' if i == 0 else 'nop') for i in range(30)]


def test_offsets_are_applied_as_bytes():
    result = variants(SOURCE, 'setup', '', ROWS)
    assert len(result) == 1
    assert '*(s32 *) ((char *) &result + (index * 0x184))' in result[0][1]
    assert 'initialize((index * 0x184) + (char *) &base, object)' in result[0][1]


def test_requires_same_target_symbols_and_simple_local():
    assert not variants(SOURCE, 'setup', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('&base, object', '&other, object'), 'setup', '', ROWS)
    assert not variants(SOURCE.replace('offset = index', 'offset = index + 1;\n    offset = index'), 'setup', '', ROWS)
    assert not variants(SOURCE.replace('extern M2C_UNK base', 'extern volatile M2C_UNK base'), 'setup', '', ROWS)
