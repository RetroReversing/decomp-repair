from decomprepair.measured_kmc_event_timestamp import variants

TIME = ('M2C_FIELD(event, s32 *, 4) = (s32) (M2C_FIELD(clock, s32 *, 0x1C) + '
        'M2C_FIELD(M2C_FIELD(voice, void **, 8), s32 *, 0xD8));')
TYPE = 'M2C_FIELD(event, s16 *, 8) = 7;'
NEXT = 'M2C_FIELD(event, s32 *, 0) = 0;'
FLOAT = 'M2C_FIELD(event, f32 *, 0xC) = value;'
INT = 'M2C_FIELD(event, s32 *, 0xC) = (s32) (value & 0xFF);'


def draft(kind, statements):
    return (f'void example(void *clock, void *voice, {kind} value) {{\n'
            '    void *event;\n    event = allocate();\n    if (event) {\n        '
            + '\n        '.join(statements) + '\n    }\n}\n')


def rows(floating):
    target = ['lw $v0, 8($s0)', 'lw $v1, 0x1c($s1)', 'lw $a0, 0xd8($v0)',
              'addiu $v0, $zero, 7', 'sh $v0, 8($a2)']
    target += ['swc1 $f20, 0xc($a2)'] if floating else ['andi $v0, $s2, 0xff', 'sw $v0, 0xc($a2)']
    target += ['sw $zero, ($a2)', 'addu $v1, $v1, $a0', 'sw $v1, 4($a2)']
    candidate = ['jal allocate', 'nop', 'sh $v0, 8($a2)']
    return [('x', target[i] if i < len(target) else 'nop',
             candidate[i] if i < len(candidate) else 'nop') for i in range(30)]


def test_stages_integer_and_float_timestamps():
    for kind, statements in [('s32', [INT, TIME, TYPE, NEXT]), ('f32', [TYPE, NEXT, TIME, FLOAT])]:
        result = variants(draft(kind, statements), 'example', '', rows(kind == 'f32'))
        assert len(result) == 1
        code = result[0][1]
        assert code.index('__repair_time = (s32)') < code.index(TYPE)
        assert code.index(TYPE) < code.index(statements[0] if kind == 's32' else FLOAT)
        assert code.index(NEXT) < code.index('s32 *, 4) = __repair_time;')


def test_requires_matching_witness_and_safe_shape():
    source = draft('f32', [TYPE, NEXT, TIME, FLOAT])
    evidence = rows(True)
    assert not variants(source, 'example', '', [('x', 'nop', right) for _, _, right in evidence])
    assert not variants(source.replace('0xD8', '0xDC'), 'example', '', evidence)
    assert not variants(source.replace(NEXT, '/* keep order */\n        ' + NEXT), 'example', '', evidence)
    assert not variants(source.replace('void *event;', 'volatile void *event;'), 'example', '', evidence)
    assert not variants(source.replace('void *event;', 's32 __repair_time;\n    void *event;'), 'example', '', evidence)
