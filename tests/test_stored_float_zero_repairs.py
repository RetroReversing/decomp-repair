from decomprepair import stored_float_zero_repairs as repair

FIELD = '*((f32 *) (((char *) arg0) + 0x44))'
SOURCE = f"""\
void f(void *arg0, int state) {{
    f32 sp5C;
    sp5C = 0.0f;
    switch (state) {{
    case 5:
        {FIELD} = 0.0f;
        break;
    }}
    {FIELD} = (f32) (({FIELD}) + 0.0f);
}}
"""


def assembly(*rows):
    return '\n'.join(f'/* {i*4:X} {0x80000000+i*4:08X} 00000000 */ {row}' for i, row in enumerate(rows))


TARGET = assembly(
    'addiu $sp, $sp, -0xf8',
    'addu $s2, $a0, $zero',
    'addu $s7, $zero, $zero',
    'sw $s7, 0x5c($sp)',
    'move $s7, $zero',
    'mtc1 $s7, $f16',
    'add.s $f2, $f2, $f16',
    'swc1 $f2, 0x44($s2)',
)


def test_splits_word_initialization_from_the_float_uses():
    [(family, candidate)] = repair.variants(SOURCE, 'f', TARGET)
    assert family == repair.FAMILY
    assert candidate.count('repair_saved_zero.bits = 0;') == 2
    assert candidate.index('repair_saved_zero.bits = 0;') < candidate.index('sp5C = 0.0f;')
    assert f'{FIELD} = repair_saved_zero.number;' in candidate
    assert '+ repair_saved_zero.number' in candidate


def test_requires_saved_zero_and_a_store_to_the_argument_field():
    for altered in (
        TARGET.replace('move $s7, $zero', 'move $s7, $v0'),
        TARGET.replace('swc1 $f2, 0x44($s2)', 'swc1 $f2, 0x40($s2)'),
        TARGET.replace('addu $s2, $a0, $zero', 'addu $s2, $a1, $zero'),
    ):
        assert not repair.variants(SOURCE, 'f', altered)


def test_skips_paths_bypassing_initialization_and_unbraced_resets():
    bypass = SOURCE.replace('    sp5C = 0.0f;', '    if (state) goto tail;\n    sp5C = 0.0f;').replace(
        f'    {FIELD} = (f32)', f'tail:\n    {FIELD} = (f32)')
    unbraced = SOURCE.replace(f'        {FIELD} = 0.0f;', f'        if (state) {FIELD} = 0.0f;')
    assert not repair.variants(bypass, 'f', TARGET)
    assert not repair.variants(unbraced, 'f', TARGET)


STACK_SOURCE = '''\
typedef struct { float x; float y; float z; } Vector;
void update(void *context) {
    union { unsigned int bits; float number; } zero;
    struct { Vector vector; } frame;
    zero.bits = (unsigned int)context & ~(unsigned int)context;
    fill(&frame.vector.x);
    frame.vector.y = zero.number;
    consume(&frame.vector.x);
    emit(frame.vector.z);
}
'''
STACK_ROWS = [
    (' ', 'jal fill', 'jal fill'),
    (' ', 'addiu $s0, $sp, 0x20', 'addiu $s0, $sp, 0x20'),
    (' ', 'move $a0, $s0', 'move $a0, $s0'),
    (' ', 'jal consume', 'jal consume'),
    ('r', 'sw $zero, 0x24($sp)', 'sw $s7, 0x24($sp)'),
]


def test_stack_vector_uses_a_word_view_for_the_proven_zero_only():
    [(label, source)] = repair.stack_word_variants(STACK_SOURCE, 'update', STACK_ROWS)
    assert label == repair.STACK_WORD
    assert 'union { Vector value; unsigned int words[3]; } vector;' in source
    assert 'frame.vector.words[1] = 0;' in source
    assert 'fill(&frame.vector.value.x);' in source
    assert 'consume(&frame.vector.value.x);' in source
    assert 'emit(frame.vector.value.z);' in source


def test_stack_word_requires_a_matching_call_offset_and_three_plain_float_fields():
    assert not repair.stack_word_variants(STACK_SOURCE, 'update', STACK_ROWS[1:3] + STACK_ROWS[-1:])
    for source in (
        STACK_SOURCE.replace('    consume(', '    receive('),
        STACK_SOURCE.replace('frame.vector.y =', 'frame.vector.z ='),
        STACK_SOURCE.replace('float z;', 'float z; int extra;'),
        STACK_SOURCE.replace('consume(&frame.vector.x)', 'consume(&frame.vector.y)'),
    ):
        assert not repair.stack_word_variants(source, 'update', STACK_ROWS)
    assert not repair.stack_word_variants(STACK_SOURCE, 'update', STACK_ROWS, max_bytes=len(STACK_SOURCE))
    assert not repair.stack_word_variants(STACK_SOURCE, 'update', STACK_ROWS, header='#define words something')


def test_stack_word_requires_positive_zero_on_all_incoming_paths():
    for changed in (
        'if (context) zero.bits = 0;',
        'zero.bits = 0x80000000U;',
        'zero.bits = 0; touch(&zero);',
        'zero.bits = 0; if (context) zero.number = 1.0f;',
    ):
        source = STACK_SOURCE.replace('zero.bits = (unsigned int)context & ~(unsigned int)context;', changed)
        assert not repair.stack_word_variants(source, 'update', STACK_ROWS)
    assert repair.stack_word_variants(STACK_SOURCE.replace('zero.number;', '0.0f;'), 'update', STACK_ROWS)


TAIL_SOURCE = '''\
void update(void *state, int arm) {
    if (arm == 2) {
        *((f32 *) (((char *) state) + 0x14)) = 0.0f;
        return;
    }
    if (arm == 3) goto clear_again;
    if (arm == 4) goto clear_again;
    return;
clear_again:
    *((f32 *) (((char *) state) + 0x14)) = 0.0f;
}
'''
TAIL_ROWS = [
    ('i', 'j update+0x20', 'j update+0x18'), (' ', 'nop', 'nop'),
    ('i', 'bc1f .L20', 'bc1f .L18'), *([(' ', 'nop', 'nop')] * 3),
    (' ', 'j update+0x2c', 'j update+0x2c'),
    (' ', 'sw $zero, 0x14($s0)', 'sw $zero, 0x14($s0)'),
    (' ', 'j update+0x2c', 'j update+0x2c'),
    (' ', 'sw $zero, 0x14($s0)', 'sw $zero, 0x14($s0)'),
    (' ', 'nop', 'nop'), (' ', 'jr $ra', 'jr $ra'), (' ', 'nop', 'nop'),
]


def test_distinguishes_the_two_identical_linked_zero_store_tails():
    [(label, text)] = repair.distinct_tail_variants(TAIL_SOURCE, 'update', TAIL_ROWS)
    assert label == repair.DISTINCT_TAIL
    assert 'repair_zero_padding[0x14]' in text
    assert 'clear_again:\n    ((RepairZeroRecord *) state)->repair_zero_field.repair_zero_bits = 0;' in text
    assert text.count('= 0.0f;') == 1
    assert not repair.distinct_tail_variants(text, 'update', TAIL_ROWS)


def test_distinct_tails_require_both_edges_the_same_store_and_literal_positive_zero():
    for rows in (
        [TAIL_ROWS[0], *([(' ', 'nop', 'nop')] * 5), *TAIL_ROWS[6:]],
        [*TAIL_ROWS[:9], (' ', 'sw $zero, 0x18($s0)', 'sw $zero, 0x18($s0)'), *TAIL_ROWS[10:]],
        [('i', 'j other+0x20', 'j other+0x18'), *TAIL_ROWS[1:]],
    ):
        assert not repair.distinct_tail_variants(TAIL_SOURCE, 'update', rows)
    assert not repair.distinct_tail_variants(TAIL_SOURCE.replace('goto clear_again;', 'return;', 1), 'update', TAIL_ROWS)
    assert not repair.distinct_tail_variants(TAIL_SOURCE.replace('= 0.0f;', '= -0.0f;'), 'update', TAIL_ROWS)
    assert not repair.distinct_tail_variants(TAIL_SOURCE, 'update', TAIL_ROWS, max_bytes=len(TAIL_SOURCE))
