import math
import struct

from decomprepair import float_negation_branch_order as repair

ASM = 'c.lt.s $f0, $f4\nnop\nbc1t .Lpositive\nmov.s $f6, $f4\nneg.s $f6, $f4\n'
SOURCE = '''void f(void) {
    f32 x;
    f32 y;
    f32 a;
    f32 b;
    a = x;
    if (!(x > 0.0f)) { a = -x; }
    b = y;
    if (!(y > 0.0f)) { b = -y; }
    consume(a, b);
}
'''


def test_each_negation_and_the_combined_child_are_offered():
    out = repair.variants(SOURCE, 'f', ASM)
    assert len(out) == 3
    assert 'a = -x;' in out[0][1] and 'b = y;' in out[0][1]
    assert 'a = -x;' in out[-1][1] and 'b = -y;' in out[-1][1]


def test_values_agree_including_signed_zero_and_nan():
    for x in (-2.0, -0.0, 0.0, 2.0, float('nan')):
        before = x if x > 0.0 else -x
        after = -x
        if x > 0.0:
            after = x
        if math.isnan(before):
            assert math.isnan(after) and math.copysign(1.0, before) == math.copysign(1.0, after)
        else:
            assert struct.pack('>f', before) == struct.pack('>f', after)


def test_rejects_missing_evidence_volatile_names_and_else():
    assert repair.variants(SOURCE, 'f', '') == []
    assert repair.variants(SOURCE.replace('f32 x;', 'volatile f32 x;'), 'f', ASM) == []
    assert all('a = -x;\n    if (x > 0.0f)' not in text
               for _, text in repair.variants(SOURCE, 'f', ASM, '#define x side_effect()'))
    assert repair.variants(SOURCE.replace('if (!(x > 0.0f)) { a = -x; }',
                                         'if (!(x > 0.0f)) { a = -x; } else { other(); }'), 'f', ASM)[0][1].count('a = x;') == 1


def test_negative_initialization_can_be_written_as_an_explicit_else():
    source = "void f(void) {\n    f32 a;\n    f32 x;\n    a = -x;\n    if (x > 0.0f) {\n        a = x;\n    }\n}\n"
    asm = "c.lt.s $f0, $f2\nbc1t .L1\nneg.s $f0, $f2\n"
    out = repair.variants(source, 'f', asm)
    assert len(out) == 1 and '} else {' in out[0][1] and 'a = -x;' in out[0][1]
