from decomprepair.byte_countdown_order import FAMILY, variants

SOURCE = """\
static inline s8 read_byte(char *pointer, int offset)
{
    return *((s8 *) (pointer + offset));
}
int update(char *record)
{
    s32 value;
    value = read_byte((char *) record, 12);
    *((u8 *) (((char *) record) + 4)) = (u8) ((*((u8 *) (((char *) record) + 4))) - 1);
    if (value < read_byte((char *) record, 16))
        return value;
    return 0;
}
"""

ROWS = [
    ('>', '', 'lb $v0, 12($s1)'),
    ('r', 'lbu $v0, 4($s1)', 'lbu $v1, 4($s1)'),
    ('<', 'lb $v1, 12($s1)', ''),
    (' ', 'lb $a0, 16($s1)', 'lb $a0, 16($s1)'),
    ('r', 'addiu $v0, $v0, -1', 'addiu $v1, $v1, -1'),
    ('r', 'sb $v0, 4($s1)', 'sb $v1, 4($s1)'),
]


def test_stage_load_without_changing_wrapping_store():
    [(family, revised)] = variants(SOURCE, 'update', ROWS)
    assert family == FAMILY
    assert 'u32 repair_countdown_byte;' in revised
    assert revised.index('repair_countdown_byte =') < revised.index('value = read_byte(')
    assert '(u8) (repair_countdown_byte - 1)' in revised
    assert variants(revised, 'update', ROWS) == []


def test_require_offsets_and_measured_order():
    assert variants(SOURCE.replace(', 16)', ', 17)'), 'update', ROWS) == []
    assert variants(SOURCE, 'update', [(' ', t, t) for _, t, _ in ROWS if t]) == []
    assert variants(SOURCE, 'update', [ROWS[0], ROWS[2], ROWS[1], *ROWS[3:]]) == []


def test_avoid_unknown_helper_and_volatile_inputs():
    assert variants(SOURCE.replace('(pointer + offset)', '(pointer + offset + 1)'), 'update', ROWS) == []
    assert variants(SOURCE, 'update', ROWS, header='typedef volatile unsigned char u8;') == []
    assert variants(SOURCE, 'update', ROWS, header='#define read_byte other_reader') == []
    assert variants(SOURCE.replace('char *record)', 'volatile char *record)'), 'update', ROWS) == []
