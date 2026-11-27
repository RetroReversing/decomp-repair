"""row_loop_param_copies: a compare-and-swap row sort with parameters held in locals and a `while` for the goto loop.

Reduced from an SN N64 sort-by-callback routine (20 -> 0): the `while` child's loop and the copies child's names are the
matched source's, together (the families compose: each alone stays at 20)."""
import re

from decomprepair import row_loop_param_copies as r

SOURCE = '''void f(s32 arg0, s32 arg1, u32 arg2, s32 (*arg3)(s32, s32)) {
    s32 temp_lo;
    s32 var_s0;
    s32 var_s3;
    u32 var_a2;
    s32 pad[4];

    var_s3 = 0;
    if (arg1 > 0) {
        var_s0 = arg1 - 1;
        __repair_rows: {
            if (var_s3 < var_s0) {
                temp_lo = var_s3 * arg2;
                do {
                    if (arg3(arg0 + temp_lo, arg0 + (var_s0 * arg2)) > 0) {
                        var_a2 = 0;
                    }
                    var_s0 -= 1;
                } while (var_s3 < var_s0);
            }
            var_s3 += 1;
            var_s0 = arg1 - 1;
        }
if (var_s3 < arg1) goto __repair_rows;
    }
}
'''


def _by(source, family):
    return [text for fam, text in r.variants(source, 'f') if fam == family]


def test_rotated_goto_loop_becomes_a_while_with_its_reset_at_the_head():
    [text] = _by(SOURCE, r.WHILE)
    assert '    var_s3 = 0;\n    while (var_s3 < arg1) {\n        var_s0 = arg1 - 1;\n        if (var_s3 < var_s0) {' in text
    assert text.rstrip().endswith('        var_s3 += 1;\n    }\n}')
    assert 'goto' not in text and '__repair_rows' not in text


def test_parameters_get_local_copies_used_in_the_body():
    text = _by(SOURCE, r.COPIES)[0]
    for ident in ('arg0', 'arg1', 'arg2'):
        assert f'    {ident}_copy = {ident};\n' in text
    assert '    s32 (*arg3_copy)(s32, s32);\n' in text and 'arg3_copy(arg0_copy + temp_lo' in text


def test_pad_shrinks_in_further_children():
    texts = _by(SOURCE, r.COPIES)
    assert len(texts) == 2 and 's32 pad[2];' in texts[1]


def test_the_two_compose_to_the_matched_loop():
    [loop] = _by(SOURCE, r.WHILE)
    text = [t for f, t in r.variants(loop, 'f') if f == r.COPIES][1]
    text = re.sub(r'\b(\w+)_copy\b', lambda m: {'arg0': 'base', 'arg1': 'n', 'arg2': 'stride', 'arg3': 'cmp'}[m[1]], text)
    assert 'while (var_s3 < n) {\n        var_s0 = n - 1;' in text
    assert 'temp_lo = var_s3 * stride;' in text and 'cmp(base + temp_lo, base + (var_s0 * stride)) > 0' in text
    assert 's32 pad[2];' in text


def test_a_body_that_does_not_end_with_the_reset_is_left_as_a_goto():
    assert _by(SOURCE.replace('            var_s0 = arg1 - 1;\n        }', '        }'), r.WHILE) == []


def test_assigned_parameter_gets_no_copy():
    assert _by(SOURCE.replace('var_s3 = 0;', 'var_s3 = 0;\n    arg2 = 4;'), r.COPIES) == []
