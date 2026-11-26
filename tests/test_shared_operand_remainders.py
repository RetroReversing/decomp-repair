"""Remainders of one variable by different constants, named in fresh locals before the statements that use them."""
from decomprepair.shared_operand_remainders import FAMILY, variants

# The shape of a HUD drawer's pulse (SN64 GCC 2.8.1, 450 -> 105 by this edit alone).
SAVED = '''extern s32 G;
void f(s32 *o) {
    s32 a;
    s32 b;

    if (o[1] != 0) {
        return;
    }
    a = 0xFF - (G % 144) * 4;
    b = 0xFF - (G % 36) * 6;
    if (a < 0x50) {
        a = 0x50;
    }
    o[0] = a + b;
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_remainders_are_named_before_their_statements():
    out = [_squash(src) for fam, src in variants(SAVED, 'f') if fam == FAMILY]
    want = 'rem144 = G % 144; rem36 = G % 36; a = 0xFF - rem144 * 4; b = 0xFF - rem36 * 6;'
    assert any(want in s and 's32 rem144; s32 rem36;' in s for s in out)
    assert any('rem36 = G % 36; rem144 = G % 144; a = 0xFF - rem144 * 4;' in s for s in out)


def test_the_operand_type_decides_the_locals_type():
    out = [_squash(s) for _, s in variants(SAVED.replace('extern s32 G;', 'extern u32 G;'), 'f')]
    assert out and all('u32 rem144;' in s for s in out)
    out = [_squash(s) for _, s in variants(SAVED.replace('extern s32 G;\n', ''), 'f', header='extern int G;\n')]
    assert out and all('s32 rem144;' in s for s in out)


def test_quotients_too_and_fresh_names():
    src = SAVED.replace('(G % 144)', '(G / 10)').replace('s32 b;', 's32 b;\n    s32 quo10;')
    out = [_squash(s) for _, s in variants(src, 'f')]
    assert any('quo10_2 = G / 10; rem36 = G % 36; a = 0xFF - quo10_2 * 4;' in s for s in out)


def test_other_shapes_are_left_alone():
    for old, new in (('(G % 36)', '(G % 144)'),          # the same operation twice: cse shares it already
                     ('(G % 36)', '(H % 36)'),           # two variables
                     ('    b = 0xFF', '    o[2] = 1;\n    b = 0xFF'),  # not adjacent
                     ('b = 0xFF - (G % 36) * 6;', 'G = 0xFF - (G % 36) * 6;')):  # assigns the operand
        assert not variants(SAVED.replace(old, new), 'f'), new
    assert not variants(SAVED.replace('extern s32 G;\n', ''), 'f')  # no declaration: type unknown
    assert not variants(SAVED.replace('extern s32 G;', 'extern volatile s32 G;'), 'f')
    assert not variants(SAVED, 'g')


def test_the_module_declares_itself():
    from decomprepair import registry
    assert FAMILY in {fam for item in registry.declared() for fam in item.families}
