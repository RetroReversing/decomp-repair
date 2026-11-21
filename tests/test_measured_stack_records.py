import pytest

from decomprepair.measured_stack_records import variants


def measured(store, tag='17'):
    return [
        ('s', 'addiu $sp, $sp, -40', 'addiu $sp, $sp, -32'),
        (' ', f'addiu $v0, $zero, {tag}', f'addiu $v0, $zero, {tag}'),
        (' ', 'addiu $a0, $a0, 44', 'addiu $a0, $a0, 44'),
        ('<', f'{store} $a1, 20($sp)', ''),
        (' ', 'addiu $a1, $sp, 16', 'addiu $a1, $sp, 16'),
        (' ', 'move $a2, $zero', 'move $a2, $zero'),
        ('s', 'sw $ra, 32($sp)', 'sw $ra, 24($sp)'),
        (' ', 'jal enqueue', 'jal enqueue'),
        (' ', 'sh $v0, 16($sp)', 'sh $v0, 16($sp)'),
        ('s', 'lw $ra, 32($sp)', 'lw $ra, 24($sp)'),
        (' ', 'jr $ra', 'jr $ra'),
        ('s', 'addiu $sp, $sp, 40', 'addiu $sp, $sp, 32'),
    ]


SOURCE = '''
void enqueue(s32 list, s16 *record, s32 delay);
void f(s32 list, {kind} value) {{
    s16 tag;
    {kind} payload;

    payload = value;
    tag = 0x11;
    enqueue(list + 44, &tag, 0);
}}
'''


@pytest.mark.parametrize(('kind', 'store'), [('s32', 'sw'), ('s16', 'sh')])
def test_attaches_eliminated_payload_to_the_escaping_record(kind, store):
    source = SOURCE.format(kind=kind)
    [(family, fixed)] = variants(source, 'f', '', measured(store))
    assert family == 'measured_tagged_stack_record'
    assert f'{kind} __repair_stack_record_data;' in fixed
    assert 's32 __repair_stack_record_tail[2];' in fixed
    assert '__repair_stack_record.__repair_stack_record_data = value;' in fixed
    assert 'enqueue(list + 44, &__repair_stack_record.__repair_stack_record_tag, 0);' in fixed


def test_requires_matching_frame_and_missing_payload_evidence():
    source = SOURCE.format(kind='s32')
    rows = measured('sw')
    assert not variants(source.replace('0x11;', '18;'), 'f', '', rows)
    assert not variants(source.replace('payload = value;', 'payload = value + 1;'), 'f', '', rows)
    assert not variants(source, 'f', '', measured('sh'))
    rows[3] = ('r', rows[3][1], 'sw $a1, 28($sp)')
    assert not variants(source, 'f', '', rows)
    rows = measured('sw')
    rows[6] = ('s', rows[6][1], 'sw $ra, 20($sp)')
    assert not variants(source, 'f', '', rows)
