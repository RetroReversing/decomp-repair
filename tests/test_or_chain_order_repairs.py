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


def test_unsigned_or_identity_is_offered_without_changing_other_operands():
    source = '''void f(u32 shade) {
        u32 high = shade << 16; u32 low = shade << 8;
        do { out = (((0xff000000 | high) | low) | shade); } while (0);
    }'''
    out = _texts(source)
    assert any('high | ((~low & 0xff000000) | low) | shade' in t for t in out)


def test_or_identity_refuses_volatile_shadowed_and_macro_operands():
    base = 'u32 f(u32 a, u32 b) { return (0xff000000 | a | b); }'
    assert not any('~a' in t for t in _texts(base.replace('u32 a', 'volatile u32 a')))
    shadowed = 'u32 f(u32 a, u32 b) { { s32 a; } return (0xff000000 | a | b); }'
    assert not any('~a' in t for t in _texts(shadowed))
    assert not any('~a' in t for t in _texts(shadowed.replace('s32 a;', 'u32 *a;')))
    assert not any('~a' in t for _, t in r.variants(base, 'f', '#define a read()'))
    assert not any('~a' in t for _, t in r.variants(base, 'f', 'typedef volatile unsigned int u32;'))
    assert not any('~a' in t for t in _texts('u32 f(s32 a, u32 b) { return (0xff000000 | a | b); }'))


def test_or_identity_keeps_the_unsigned_int_width():
    source = 'u32 f(u32 a, u32 b) { return (0xff000000 | a | b); }'
    assert any('~a' in t for t in _texts(source))
    for literal in ('0xff000000UL', '0x100000000', '4294967295'):
        assert not any('~a' in t for t in _texts(source.replace('0xff000000', literal)))
    for value in (0, 1, 0xff, 0x80000000, 0xffffffff):
        for mask in (0, 0xff, 0xff000000, 0xffffffff):
            assert value | ((~value & 0xffffffff) & mask) == value | mask


PACK = '''void f(u32 shade) {
    u32 high = shade << 16; u32 low = shade << 8;
    do { out->word = (((0xff000000 | high) | low) | shade); } while (0);
}'''


def _weighted(source=PACK, header=''):
    return [text for family, text in r.variants(source, 'f', header) if family == 'weighted_or_pack']


def test_weighted_pack_stages_the_unsigned_or_after_both_shifts():
    [result] = _weighted()
    assert 'high = shade << 16;' in result and 'low = shade << 8;' in result
    assert '__repair_or_part = low | 0xff000000;' in result
    assert 'high |= __repair_or_part;' in result
    assert 'out->word = high | shade;' in result
    identity = PACK.replace('(((0xff000000 | high) | low) | shade)',
                            '(((high | ((~low & 0xff000000) | low)) | shade))')
    assert len(_weighted(identity)) == 1


def test_weighted_pack_refuses_unproved_scope_and_expression_shapes():
    assert not _weighted(PACK.replace('} while (0);', '} while (0); sink(high);'))
    assert not _weighted(PACK.replace('u32 shade', 'volatile u32 shade'))
    assert not _weighted(PACK, '#define low read()')
    assert not _weighted(PACK, '#define u32 unsigned int')
    assert not _weighted(PACK, 'typedef volatile unsigned int u32;')
    assert not _weighted(PACK.replace('u32 low =', 'volatile u32 low ='))
    assert not _weighted(PACK.replace('u32 low =', 'u32 *low; u32 low ='))
    # These flattened tokens are similar, but the parenthesization changes their meaning.
    changed = PACK.replace('(((0xff000000 | high) | low) | shade)',
                           '(high | (~low & (0xff000000 | low)) | shade)')
    assert not _weighted(changed)
