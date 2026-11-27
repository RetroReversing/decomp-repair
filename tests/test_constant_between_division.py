from decomprepair import constant_between_division as repair

SOURCE = '''void func(float *v) {
    float inv;
    float zero;

    inv = 1.0f / sqrtf(v[0] * v[0]);
    v[0] *= inv;
    zero = 0.0f;
    v[1] = zero;
}
'''


def test_the_constant_goes_between_the_call_and_the_division():
    (family, child), = repair.variants(SOURCE, 'func')
    assert family == 'constant_between_division'
    assert ('    inv = sqrtf(v[0] * v[0]);\n    zero = 0.0f;\n    inv = 1.0f / inv;\n    v[0] *= inv;\n'
            '    v[1] = zero;\n') in child


def test_a_constant_read_between_stays():
    assert repair.variants(SOURCE.replace('v[0] *= inv;', 'v[0] *= zero;'), 'func') == []


def test_a_constant_in_another_block_stays():
    assert repair.variants(SOURCE.replace('    zero = 0.0f;\n', '    if (v) { zero = 0.0f; }\n'), 'func') == []
