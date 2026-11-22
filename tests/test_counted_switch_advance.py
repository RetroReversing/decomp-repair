from decomprepair.counted_switch_advance import FAMILY, variants

SOURCE = """
void run(int state, int enabled, void *record)
{
    u8 previous;
    switch (state) {
    case 1:
        if (enabled)
        {
            previous = *((u8 *) (((char *) record) + 12));
            *((u8 *) (((char *) record) + 12)) = (u8) (previous + 1);
            if (((s8) previous) >= 3)
            {
                goto reset_state;
            }
            advance(record);
        }
        else
        {
        reset_state:
            *((s8 *) (((char *) record) + 7)) = 2;
        }
        break;
    case 2:
        stop(record);
        break;
    }
}
"""

SHARED = [
    'lbu $v0, 12($s1)',
    'addiu $v1, $v0, 1',
    'sll $v0, $v0, 0x18',
    'sra $v0, $v0, 0x18',
    'slti $v0, $v0, 3',
]
ROWS = [
    *[(' ', op, op) for op in SHARED],
    ('|', 'bnez $v0, .Ladvance', 'beqz $v0, .Lreset'),
    ('<', 'sb $v1, 12($s1)', ''),
    ('o', 'addiu $v0, $zero, 2', 'nop'),
    ('o', 'j .Lexit', 'j .Lexit2'),
    ('i', 'sb $v0, 7($s1)', 'sb $v1, 12($s1)'),
]


def test_uses_advance_branch_and_shared_reset_with_exact_signed_test():
    [(family, revised)] = variants(SOURCE, 'run', ROWS)
    assert family == FAMILY
    assert 'if (((s8) previous) < 3) goto repair_advance_state;' in revised
    assert revised.index('= (u8) (previous + 1);') < revised.index('goto repair_advance_state;')
    assert revised.index('+ 7)) = 2;') < revised.index('repair_advance_state:')
    assert 'reset_state:' not in revised
    assert variants(revised, 'run', ROWS) == []


def test_requires_same_offsets_and_single_entry_to_old_label():
    assert variants(SOURCE.replace('+ 7)) = 2;', '+ 8)) = 2;'), 'run', ROWS) == []
    assert variants(SOURCE.replace('        stop(record);', '        goto reset_state;'), 'run', ROWS) == []
    assert variants(SOURCE.replace('        break;\n    case 2:', '        stop(record);\n    case 2:'), 'run', ROWS) == []
    assert variants(SOURCE, 'run', [(' ', t, t) for _, t, _ in ROWS]) == []
