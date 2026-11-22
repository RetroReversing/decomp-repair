from decomprepair import or_chain_order_repairs as r

DRAFT = '''void f(s32 x, s32 y)
{
    s32 var_v0;
    var_v0 = x;
    *((s32 *) (((char *) y) + 0)) = (s32) (((var_v0 * 4) | 0xF6000000) | y);
    g(var_v0);
}
'''


def _texts(source=DRAFT):
    return [t for _, t in r.variants(source, 'f')]


def test_the_literal_goes_first_in_every_order_of_the_rest():
    out = _texts()
    assert any('(s32) (0xF6000000 | y | var_v0 * 4);' in t for t in out)
    assert any('(s32) (0xF6000000 | var_v0 * 4 | y);' in t for t in out)
    assert len(out) == 2


def test_the_function_is_otherwise_unchanged():
    for text in _texts():
        assert text.count('\n') == DRAFT.count('\n')
        assert text.replace('0xF6000000 | y | var_v0 * 4', 'X').replace('0xF6000000 | var_v0 * 4 | y', 'X') != DRAFT


def test_a_call_among_the_operands_is_left_alone():
    assert _texts(DRAFT.replace('| y)', '| h(y))')) == []


def test_two_operands_or_two_literals_are_left_alone():
    assert _texts(DRAFT.replace('((var_v0 * 4) | 0xF6000000) | y', 'var_v0 | 0xF6000000')) == []
    assert _texts(DRAFT.replace('((var_v0 * 4) | 0xF6000000) | y', '(var_v0 | 0xF6000000) | 0xFF')) == []


def test_a_logical_or_is_not_a_bit_chain():
    assert _texts(DRAFT.replace('((var_v0 * 4) | 0xF6000000) | y', 'x || y || 3')) == []
