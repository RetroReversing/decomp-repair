from decomprepair import call_span_locals as spans

SOURCE = '''void f(Gfx **dl, u8 s, u8 t) {
    switch (s) {
    case 1:
        load((*dl)++, data, s * 32, t * 32, s * 32 + 31, (t + 1) * 32 - 1, 0);
        break;
    }
}
'''


def test_the_corners_of_a_span_are_staged_in_halfword_locals():
    family, out = spans.variants(SOURCE, 'f')[0]
    assert family == 'call_span_locals'
    assert 's16 span0 = s * 32;' in out and 's16 span1 = t * 32;' in out
    assert 's16 end0 = span0 + 32;' in out and 's16 end1 = span1 + 32;' in out
    assert 'load((*dl)++, data, span0, span1, end0 - 1, end1 - 1, 0);' in out


def test_the_first_pair_alone_and_wider_types_are_offered():
    outs = [out for _, out in spans.variants(SOURCE, 'f')]
    assert any('s32 span0' in out for out in outs)
    assert any('span1' not in out and '(t + 1) * 32 - 1' in out for out in outs)


def test_arguments_that_are_not_a_span_are_left_alone():
    assert spans.variants(SOURCE.replace('+ 31', '+ 30').replace('(t + 1) * 32 - 1', 't'), 'f') == []
    assert spans.variants('void f(s32 i) {\n    if (g(i * 4, i * 4 + 3)) {\n    }\n}\n', 'f') == []
