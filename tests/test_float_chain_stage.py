"""A float assigned from a chain of operations, written one operation per statement."""
from decomprepair.float_chain_stage import FAMILY, variants

# The tail of a text-layout function (KMC GCC 2.7.2): a scale from a count, clamped to 1.0.
SAVED = '''void f(f32 total, s16 count, void *out) {
    f32 scale;
    if (count != 0) {
        scale = ((total / ((f32) count)) * 30.0f) - 15.0f;
        if (scale < 1.0f) {
            scale = 1.0f;
        }
        G(out, 0x14) = scale;
    }
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_chain_is_written_one_operation_per_statement():
    out = [_squash(src) for fam, src in variants(SAVED, 'f') if fam == FAMILY]
    assert any('scale = total / ((f32) count); scale = scale * 30.0f; scale = scale - 15.0f;' in s for s in out)


def test_the_compound_spelling_is_offered_too():
    out = [_squash(src) for _, src in variants(SAVED, 'f')]
    assert any('scale = total / ((f32) count); scale *= 30.0f; scale -= 15.0f;' in s for s in out)


def test_every_chain_of_the_function_together_is_one_child():
    src = SAVED.replace('G(out, 0x14) = scale;', 'scale = (scale + 2.0f) * 3.0f;\n        G(out, 0x14) = scale;')
    out = [_squash(s) for _, s in variants(src, 'f')]
    assert any('scale = scale + 2.0f; scale = scale * 3.0f;' in s and 'scale = total / ((f32) count);' in s for s in out)


def test_a_single_operation_is_left_to_compound_operand_split():
    assert variants('void f(f32 a, f32 b) { f32 v; v = a + b; G(v); }', 'f') == []


def test_an_operand_that_mentions_the_variable_is_left_alone():
    assert variants('void f(f32 a) { f32 v; v = a * 2.0f; v = (v / a) * 3.0f - v; G(v); }', 'f') == []


def test_a_call_in_the_chain_is_left_alone():
    assert variants('void f(f32 a) { f32 v; v = (a * H(a)) - 1.0f; G(v); }', 'f') == []
