from decomprepair import dead_multiply_high as repair

DRAFT = '''void f(s32 *p) {
    s32 temp_hi;

    temp_hi = MULT_HI((p[0] - p[1]), 0x66666667);
    p[2] = (p[0] - p[1]) % 5;
    play(0x84, temp_hi);
}
'''
CALLEES = 's32 play(s16 arg0) {\n    return 0;\n}\n'


def sources(text, callees=''):
    return [child for _, child in repair.variants(text, 'f', callees)]


def test_trims_the_stray_argument_and_the_multiply_it_leaves_dead():
    assert sources(DRAFT, CALLEES) == ['void f(s32 *p) {\n\n    p[2] = (p[0] - p[1]) % 5;\n    play(0x84);\n}\n']


def test_removes_a_multiply_nothing_reads():
    text = DRAFT.replace('play(0x84, temp_hi)', 'play(0x84)')
    assert sources(text) == ['void f(s32 *p) {\n\n    p[2] = (p[0] - p[1]) % 5;\n    play(0x84);\n}\n']


def test_keeps_a_multiply_that_is_read_or_has_a_call():
    assert sources(DRAFT) == []
    assert sources(DRAFT.replace('(p[0] - p[1]), 0x', 'next(), 0x').replace('play(0x84, temp_hi)', 'play(0x84)')) == []
