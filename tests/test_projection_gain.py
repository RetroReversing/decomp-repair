"""Replace repeated literal operands only with a compatible dead local."""

from decomprepair.projection_gain import FAMILY, variants

SOURCE = """float sine(float);
float cosine(float);
void reduce(char *record, float angle, int mode)
{
    float gain;
    float x;
    float y;
    if (mode) {
        *((f32 *) (((char *) record) + 0x18)) = 0.5f;
        x = sine(angle) * 0.5f;
        y = cosine(angle) * 0.5f;
        use(x, y);
    } else {
        gain = 0.5f;
        *((f32 *) (((char *) record) + 0x18)) = gain;
        x = gain * sine(angle);
        gain = gain * cosine(angle);
        use(x, gain);
    }
}
"""


def sequence(register, *, donor=False):
    first = f'mul.s $f0, {register}, $f0' if donor else f'mul.s $f0, $f0, {register}'
    second = f'mul.s {register}, {register}, $f0' if donor else first
    return [
        'lui $at, 0x3f00', 'ori $at, $at, 0', f'mtc1 $at, {register}', 'nop',
        f'swc1 {register}, 0x18($s0)', 'jal sine', 'nop', first, 'jal cosine', 'nop', second,
        'jal use',
    ]


DEMAND = [(' ' if left == right else 'r', left, right)
          for left, right in zip(sequence('$f26'), sequence('$f20'))]
DONOR = [(' ', op, op) for op in sequence('$f26', donor=True)]
ROWS = DEMAND + DONOR


def test_named_holder_keeps_write_and_multiply_order():
    [(family, changed)] = variants(SOURCE, 'reduce', ROWS)
    assert family == FAMILY
    assert """        gain = 0.5f;
        *((f32 *) (((char *) record) + 0x18)) = gain;
        x = sine(angle) * gain;
        y = cosine(angle) * gain;""" in changed


def test_requires_confirmed_holder_and_exact_literal_field_and_calls():
    assert not variants(SOURCE, 'reduce', DEMAND)
    assert not variants(SOURCE, 'reduce', DONOR)
    assert not variants(SOURCE, 'reduce', DEMAND + [(' ', op, op) for op in sequence('$f24', donor=True)])
    assert not variants(SOURCE.replace('0.5f', '0.25f'), 'reduce', ROWS)
    assert not variants(SOURCE.replace('0x18', '0x20'), 'reduce', ROWS)
    assert not variants(SOURCE.replace('cosine(angle)', 'other(angle)'), 'reduce', ROWS)


def test_rejects_escaped_or_live_holder_and_unbraced_control_body():
    assert not variants(SOURCE.replace('    if (mode)', '    send(&gain);\n    if (mode)'), 'reduce', ROWS)
    assert not variants(SOURCE.replace('        use(x, y);', '        use(x, y, gain);'), 'reduce', ROWS)
    assert not variants(SOURCE.replace('    if (mode) {', '    if (mode) {\n        if (mode > 1)'), 'reduce', ROWS)
    assert not variants(SOURCE, 'reduce', ROWS, header='#define gain global_value')
    assert not variants(SOURCE.replace('    float gain;', '    f32 gain;'), 'reduce', ROWS,
                        header='typedef double f32;')
