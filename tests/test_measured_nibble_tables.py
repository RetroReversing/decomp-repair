from decomprepair.measured_nibble_tables import variants

SOURCE = '''extern M2C_UNK bytes;
extern M2C_UNK record;
extern M2C_UNK tablea;
extern M2C_UNK tableb;
extern M2C_UNK tablec;
extern u16 outa;
extern u16 outb;
void update(void) {
    u32 upper; u8 value;
    value = *(&bytes + M2C_FIELD(&record, u8 *, 0));
    upper = value >> 4;
    if ((value & 0xF) == 6) {
        M2C_FIELD(&record, u16 *, 5) = (u16) *(&tablea + (upper * 2));
    } else {
        outa = *(&tableb + (upper * 2));
    }
    outb = *(&tablec + ((value & 0xF) * 2));
}
'''
SYMS = ['bytes', 'record', 'tablea', 'tableb', 'tablec', 'outa', 'outb']
TARGET = ['sll $v0, $v0, 1'] * 3 + ['andi $v1, $a0, 15', 'srl $v0, $a0, 4']
TARGET += [item for name in SYMS for item in (f'lui $at, %hi({name})', f'addiu $at, $at, %lo({name})')]
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         'sll $v0, $a1, 3' if i < 2 else 'nop') for i in range(30)]


def test_recovers_table_widths():
    result = variants(SOURCE, 'update', '', ROWS)
    assert len(result) == 1
    assert 'extern u8 bytes[];' in result[0][1]
    assert 'extern u16 tablea[];' in result[0][1]
    assert 'tablea[value >> 4]' in result[0][1]


def test_rejects_unproven_widths_and_declarations():
    assert not variants(SOURCE, 'update', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE, 'update', 'extern int tablea;', ROWS)
    assert not variants(SOURCE.replace('extern M2C_UNK bytes', 'extern volatile M2C_UNK bytes'), 'update', '', ROWS)
    assert not variants(SOURCE.replace('upper = value', '/* note */ upper = value'), 'update', '', ROWS)
