"""shared_return_hoist and param_difference_reuse: an N64 interpolation's layout and reused float parameters.

Synthetic shape of a 63-instruction function built with GCC 2.7.2 -O1 (2655 -> 0)."""
from decomprepair import param_difference_reuse, shared_return_hoist

SOURCE = '''f32 mix(f32 a, f32 b, f32 lo, f32 hi) {
    f32 d;
    f32 e;
    f32 r;
    f32 num;
    f32 den;

    d = lo - a;
    e = hi - b;
    if (d == 0.0f) {
        if (a != b) {
            num = a + b;
            if (num != 0.0f) {
                return num;
            }
            goto block_4;
        }
        goto block_4;
    }
    r = 1.0f / d;
    if (e != 0.0f) {
        num = r * e;
        den = r + e;
        goto block_9;
    }
    if (a == b) {
        num = e - r;
        den = e + r;
block_9:
        return num / den;
    }
block_4:
    return 0.5f;
}
'''


def _texts(module, source=SOURCE):
    return [text for family, text in module.variants(source, 'mix') if family == module.FAMILY]


def test_the_shared_return_moves_to_its_first_site():
    text, = _texts(shared_return_hoist)
    assert '        if (a == b) {\nblock_4:\n            return 0.5f;\n        }\n        num = a + b;' in text
    assert text.rstrip().endswith('    goto block_4;\n}')
    assert text.count('return 0.5f;') == 1


def test_nothing_without_the_double_jump_or_a_literal_return():
    assert not _texts(shared_return_hoist, SOURCE.replace('            goto block_4;\n        }\n        goto block_4;',
                                                          '        }\n        goto block_4;'))
    assert not _texts(shared_return_hoist, SOURCE.replace('return 0.5f;', 'return a;'))


def test_differences_and_reciprocals_go_into_the_parameters():
    texts = _texts(param_difference_reuse)
    both = [t for t in texts if 'lo = lo - a;' in t and 'lo = 1.0f / lo;' in t]
    assert both and all('f32 d;' not in t and 'f32 r;' not in t and 'hi = hi - b;' in t for t in both)
    assert any('block_4:\n            return 0.5f;' in t for t in both)
    assert any('return num / den;' in t and 'den_b = e + r' not in t and 'goto block_9;' not in t for t in texts)


def test_a_parameter_read_later_is_kept():
    texts = _texts(param_difference_reuse, SOURCE.replace('        num = r * e;', '        num = r * e * lo;'))
    assert not any('lo = lo - a;' in t for t in texts)
