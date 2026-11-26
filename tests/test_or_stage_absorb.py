"""A staged `|` local that takes one more operand of the final chain."""
from decomprepair import or_stage_absorb as r

SOURCE = '''void f(unsigned int *p, int arg) {
    u32 a;
    s32 temp2;
    u32 word;

    a = arg & 0xFF;
    temp2 = (a << 0x18) | (a << 0x10);
    word = a | (temp2 | (a << 8));
    *p = word;
}
'''
WANT = '''    temp2 = (a << 0x18) | (a << 0x10) | (a << 8);
    word = temp2 | a;
'''


def test_the_last_operand_moves_into_the_stage():
    out = [t for _, t in r.variants(SOURCE, 'f')]
    assert any(WANT in t for t in out)
    assert all(t != SOURCE for t in out)


def test_nothing_when_the_local_is_used_elsewhere_or_a_call_is_in_the_chain():
    assert r.variants(SOURCE.replace('*p = word;', '*p = word + temp2;'), 'f') == []
    assert r.variants(SOURCE.replace('(a << 8)', 'g(a)'), 'f') == []


def test_it_declares_itself():
    assert r.REPAIR['families'] == ('or_stage_absorb',)
