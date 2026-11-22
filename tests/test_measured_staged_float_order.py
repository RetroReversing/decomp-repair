from decomprepair.measured_staged_float_order import FAMILY, variants

SOURCE = """
static inline float sum_field(float *address, float delta) { return *address + delta; }
void f(void *base) {
    float a;
    float b;
    float c;
    float x;
    float y;
    float z;
    x = 1.0f;
    y = 2.0f;
    z = 3.0f;
    a = sum_field((float *) (((char *) base) + 0x4), x);
    b = sum_field((float *) (((char *) base) + 0x8), y);
    c = sum_field((float *) (((char *) base) + 0xC), z);
    *((float *) (((char *) base) + 0x4)) = a;
    *((float *) (((char *) base) + 0x8)) = b;
    *((float *) (((char *) base) + 0xC)) = c;
}
"""
ROWS = [('i', 'swc1 $f4, 0xc($s2)', 'swc1 $f4, 0x8($s2)')]


def test_paired_float_order_keeps_captures_ahead_of_stores():
    choices = variants(SOURCE, 'f', ROWS)
    assert len(choices) == 11
    assert all(family == FAMILY for family, _ in choices)
    for _, text in choices:
        assert text.index('c = sum_field') < text.index(' = a;')
    assert any(text.index('c = sum_field') < text.index('b = sum_field')
               and text.index(' = b;') < text.index(' = c;') < text.index(' = a;')
               for _, text in choices)


def test_rejects_aliasing_destinations_volatile_inputs_and_impure_helpers():
    for before, after in (
        ('+ 0xC', '+ 0x8'),
        ('float y;', 'volatile float y;'),
        ('void *base', 'void *volatile base'),
        ('return *address + delta;', 'return next() + *address + delta;'),
    ):
        assert not variants(SOURCE.replace(before, after), 'f', ROWS)
    assert not variants(SOURCE, 'f', [])


GLOBAL_SOURCE = """
extern float bias;
static inline float sum_field(float *address, float delta) { return *address + delta; }
void f(void *base, float x, float y, float z) {
    union { unsigned int bits; float number; } delta;
    float a;
    float b;
    float c;
    float d;
    float e;
    float f;
    delta.bits = 0;
    a = sum_field((float *) (((char *) base) + 0x4), x);
    b = sum_field((float *) (((char *) base) + 0x8), y);
    c = sum_field((float *) (((char *) base) + 0xC), bias);
    d = sum_field((float *) (((char *) base) + 0x10), z);
    e = sum_field((float *) (((char *) base) + 0x14), y);
    f = sum_field((float *) (((char *) base) + 0x18), delta.number);
    *((float *) (((char *) base) + 0xC)) = c;
    *((float *) (((char *) base) + 0x8)) = b;
    *((float *) (((char *) base) + 0x4)) = a;
    *((float *) (((char *) base) + 0x10)) = d;
    *((float *) (((char *) base) + 0x14)) = e;
    *((float *) (((char *) base) + 0x18)) = f;
}
"""
GLOBAL_ROWS = [
    ('i', 'lwc1 $f6, 0xc($s2)', 'lwc1 $f2, %lo(bias)($at)'),
    ('i', 'lwc1 $f2, %lo(bias)($at)', 'lwc1 $f6, 0xc($s2)'),
    ('i', 'swc1 $f4, 0x4($s2)', 'swc1 $f4, 0xc($s2)'),
    (' ', 'swc1 $f8, 0x8($s2)', 'swc1 $f8, 0x8($s2)'),
    ('i', 'swc1 $f6, 0xc($s2)', 'swc1 $f6, 0x4($s2)'),
    (' ', 'swc1 $f4, 0x10($s2)', 'swc1 $f4, 0x10($s2)'),
    (' ', 'swc1 $f4, 0x14($s2)', 'swc1 $f4, 0x14($s2)'),
    (' ', 'swc1 $f4, 0x18($s2)', 'swc1 $f4, 0x18($s2)'),
]


def test_global_capture_can_inline_word_backed_terminal_from_store_evidence():
    choices = variants(GLOBAL_SOURCE, 'f', GLOBAL_ROWS)
    assert len(choices) == 18
    assert all(family == FAMILY for family, _ in choices)
    assert all(text.index('f = ') < min(text.index(f' = {local};') for local in 'abcdef') for _, text in choices)
    assert any('c = (float)' in text and 'f = (float)' in text
               and [text.index(f' = {local};') for local in 'aecdbf']
               == sorted(text.index(f' = {local};') for local in 'aecdbf')
               for _, text in choices)


def test_global_capture_rejects_escaped_results_and_volatile_global():
    for source in (
        GLOBAL_SOURCE.replace('extern float bias;', 'extern volatile float bias;'),
        GLOBAL_SOURCE.replace('delta.bits = 0;', 'use(&a);\n    delta.bits = 0;'),
    ):
        assert not variants(source, 'f', GLOBAL_ROWS)
    assert not variants(GLOBAL_SOURCE, 'f', GLOBAL_ROWS[1:])
    assert not variants(GLOBAL_SOURCE, 'f', [*GLOBAL_ROWS[:1],
                        ('i', GLOBAL_ROWS[1][1], 'lwc1 $f6, 0xc($s3)'), *GLOBAL_ROWS[2:]])


def test_global_capture_leaves_volatile_terminal_and_requires_all_target_stores():
    cases = (
        (GLOBAL_SOURCE.replace('float number;', 'volatile float number;'), GLOBAL_ROWS),
        (GLOBAL_SOURCE, GLOBAL_ROWS[:-1]),
    )
    for source, rows in cases:
        choices = variants(source, 'f', rows)
        assert len(choices) == 7
        assert all('c = (float)' in text and 'f = sum_field' in text for _, text in choices)


def _mixed_stack_source():
    return GLOBAL_SOURCE.replace('float y, float z)', 'float y)').replace('    float a;', '''    struct {
        volatile float speed;
    } frame;
    float z;
    float a;''').replace('    delta.bits = 0;', '''    z = 1.0f;
    frame.speed = 0.0f;
    delta.bits = 0;''').replace(
        'c = sum_field((float *) (((char *) base) + 0xC), bias);',
        'c = (float) ((*(float *) (((char *) base) + 0xC)) + bias);',
    ).replace('sum_field((float *) (((char *) base) + 0x14), y)',
              'sum_field((float *) (((char *) base) + 0x14), frame.speed)')


def test_staged_capture_split_requires_a_crossed_stack_load_and_independent_scalars():
    rows = [
        ('i', 'lwc1 $f6, 0x10($s2)', 'lwc1 $f2, 0x3c($sp)'),
        (' ', 'add.s $f8, $f8, $f16', 'add.s $f8, $f8, $f16'),
        ('i', 'lwc1 $f16, 0x3c($sp)', 'lwc1 $f6, 0x10($s2)'),
        *GLOBAL_ROWS[2:],
    ]
    source = _mixed_stack_source()
    [(family, candidate)] = variants(source, 'f', rows)
    assert family == FAMILY
    assert candidate.index('e = *') < candidate.index('d = *')
    assert candidate.index('d = (float) (d + z);') < candidate.index(' = a;')
    assert 'c = (float) (c + bias);' in candidate
    for changed in (
        source.replace('float z;', 'volatile float z;'),
        source.replace('float d;', 'volatile float d;'),
        source.replace('e = sum_field', 'use(&e);\n    e = sum_field'),
        source.replace('e = sum_field', 'base = changed;\n    e = sum_field'),
        source.replace('volatile float speed;', 'float speed;'),
    ):
        assert not variants(changed, 'f', rows)
    assert not variants(source, 'f', rows[1:])


def test_split_stores_try_the_first_store_against_other_nonterminal_stores():
    source = _mixed_stack_source()
    for local, offset, delta in zip('abcdef', ('4', '8', 'C', '10', '14', '18'),
                                    ('x', 'y', 'bias', 'z', 'frame.speed', 'delta.number')):
        start = source.index(f'    {local} = ')
        end = source.index(';\n', start) + 2
        source = source[:start] + (
            f'    {local} = *(float *) (((char *) base) + 0x{offset});\n'
            f'    {local} = (float) ({local} + {delta});\n'
        ) + source[end:]
    choices = variants(source, 'f', GLOBAL_ROWS[2:])
    assert len(choices) == 4
    assert all(candidate.index('f = (float)') < candidate.index(' = a;')
               and candidate.index(' = f;') > candidate.index(' = a;')
               for _, candidate in choices)
    assert choices[2][1].index(' = d;') < choices[2][1].index(' = b;')
    assert not variants(source.replace('float d;', 'volatile float d;'), 'f', GLOBAL_ROWS[2:])
