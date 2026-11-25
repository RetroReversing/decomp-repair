import struct

from decomprepair import registry
from decomprepair.pool_word_literal_swap import FAMILY, REPAIR, variants

WORD = struct.unpack('>I', struct.pack('>f', 500.0))[0]
NEG = struct.unpack('>I', struct.pack('>f', -150.0))[0]
SOURCE = """f32 limit(f32 a, f32 b) {
    if (a < 500.0f) {
        return b * 500.0f;
    }
    return a - 150.0f;
}
"""
ASM = "lui $at, %hi(D_8000930C)\nlwc1 $f2, %lo(D_8000930C)($at)\n"


def kids(source=SOURCE, words=None, asm=ASM, header=''):
    words = {'D_8000930C': WORD} if words is None else words
    return [c for f, c in variants(source, 'limit', header=header, asm=asm, words=words) if f == FAMILY]


def test_every_use_of_the_literal_names_the_pool_word_and_it_is_declared():
    out = kids()
    assert 'extern f32 D_8000930C;\nf32 limit' in out[0]
    assert out[0].count('D_8000930C') == 3 and '500.0f' not in out[0]


def test_a_const_declaration_and_a_first_use_only_child_follow():
    out = kids()
    assert 'extern const f32 D_8000930C;' in out[1]
    assert '(a < D_8000930C)' in out[2] and 'b * 500.0f' in out[2]


def test_a_declared_symbol_is_not_declared_again_and_a_double_is_skipped():
    out = kids(header='extern f32 D_8000930C;\n')
    assert out and 'extern' not in out[0].replace('extern f32 D_8000930C;', '')
    assert not kids(header='extern f64 D_8000930C;\n')


def test_a_negative_literal_is_named_whole_and_a_subtraction_keeps_its_minus():
    out = kids(SOURCE.replace('a - 150.0f', 'a * -150.0f'), words={'D_X': NEG}, asm='lui $at, %hi(D_X)\nlwc1 $f2, %lo(D_X)($at)\n')
    assert out and 'a * D_X' in out[0]
    positive = kids(SOURCE.replace('a - 150.0f', 'a -150.0f'), words={'D_Y': struct.unpack('>I', struct.pack('>f', 150.0))[0]},
                    asm='lui $at, %hi(D_Y)\nlwc1 $f2, %lo(D_Y)($at)\n')
    assert positive and 'a -D_Y' in positive[0]


def test_the_target_must_load_it_as_a_float_through_at():
    assert not kids(asm='lui $v0, %hi(D_8000930C)\nlw $v1, %lo(D_8000930C)($v0)\n')
    assert not kids(words={})


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
