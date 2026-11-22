"""Preserve two clears while an earlier field read feeds the measured call slot."""

from decomprepair.field_copy_before_clear import FAMILY, variants

SOURCE = '''
void prepare(char *dest, char *input)
{
    *((float *) (((char *) dest) + 12)) = 0.0f;
    *((float *) (((char *) dest) + 20)) = 0.0f;
    *((float *) (((char *) dest) + 16)) = (float) (*((float *) (((char *) input) + 4)));
    send(dest, 7);
}
'''
ROWS = [
    (' ', 'sw $zero, 12($s2)', 'sw $zero, 12($s2)'),
    ('o', '', 'sw $zero, 20($s2)'),
    (' ', 'lwc1 $f0, 4($a1)', 'lwc1 $f0, 4($a1)'),
    (' ', 'move $a0, $s2', 'move $a0, $s2'),
    (' ', 'addiu $a1, $zero, 7', 'addiu $a1, $zero, 7'),
    ('o', 'sw $zero, 20($s2)', ''),
    (' ', 'jal send', 'jal send'),
    (' ', 'swc1 $f0, 16($s2)', 'swc1 $f0, 16($s2)'),
]


def test_snapshots_input_before_the_second_clear_only():
    [(family, changed)] = variants(SOURCE, 'prepare', ROWS)
    assert family == FAMILY
    first = changed.index('dest) + 12)) = 0.0f;')
    capture = changed.index('float repair_field_snapshot =')
    second = changed.index('dest) + 20)) = 0.0f;')
    store = changed.index('dest) + 16)) = (float) repair_field_snapshot;')
    assert first < capture < second < store < changed.index('send(dest, 7);')


def test_preserves_a_local_word_clear_before_the_snapshot():
    source = SOURCE.replace('{\n', '{\n    union { unsigned word; float value; } reset;\n', 1).replace(
        '    *((float *) (((char *) dest) + 20)) = 0.0f;',
        '    reset.word = 0;\n    *((float *) (((char *) dest) + 20)) = reset.value;',
    )
    [(_, changed)] = variants(source, 'prepare', ROWS)
    assert changed.index('reset.word = 0;') < changed.index('float repair_field_snapshot =')


def test_requires_matching_offsets_bases_callee_and_delay_slot():
    assert not variants(SOURCE, 'prepare', ROWS[:-1])
    assert not variants(SOURCE.replace('send(dest, 7)', 'send(dest, 8)'), 'prepare', ROWS)
    assert not variants(SOURCE.replace('send(dest, 7)', 'send(input, 7)'), 'prepare', ROWS)
    assert not variants(SOURCE.replace('dest) + 20', 'dest) + 16'), 'prepare', ROWS)
    assert not variants(SOURCE.replace('input) + 4', 'dest) + 4'), 'prepare', ROWS)
