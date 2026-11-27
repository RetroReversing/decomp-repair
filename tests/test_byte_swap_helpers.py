"""byte_swap_helpers: m2c's expanded byte swaps written as inline helpers, and a shared dividend word."""
from decomprepair import byte_swap_helpers as repair

SWAP = '((((({x} & 0xFF) << 8) + ((u32) ({x} & 0xFF00) >> 8)) << 0x10) + ((({t} & 0xFF) << 8) + ({t} >> 8)))'

SOURCE = f'''void load(u32 *in, s32 *out, u16 *pair) {{
    u32 word;
    u32 high;
    u32 next;
    u32 top;
    u16 half;

    word = in[0];
    high = word >> 0x10;
    out[0] = (s32) {SWAP.format(x="word", t="high")} / 4;
    next = in[1];
    top = next >> 0x10;
    out[1] = (s32) ((s32) {SWAP.format(x="next", t="top")} / 4);
    half = pair[0];
    pair[0] = (u16) (((half & 0xFF) << 8) + (half >> 8));
}}
'''


def children(source, name='load'):
    return dict(repair.variants(source, name))


def test_swaps_become_helpers_and_the_dividend_is_shared():
    out = children(SOURCE)[repair.BOTH]
    assert 'static __inline__ u32 repair_swap16(u16 v)' in out
    assert out.index('repair_swap32(u32 v)') < out.index('void load(')
    assert 'repair_word = (repair_swap32(word));\n    out[0] = repair_word / 4;' in out
    assert 'repair_word = (repair_swap32(next));\n    out[1] = repair_word / 4;' in out
    assert 'pair[0] = (u16) repair_swap16(pair[0]);' in out
    for gone in ('high', 'u32 top;', 'u16 half;', '0x10;'):
        assert gone not in out.split('void load(')[1]


def test_the_unstaged_helper_is_one_expression():
    made = children(SOURCE)
    assert 'return (repair_swap16(v) << 16) + repair_swap16(v >> 16);' in made[repair.PLAIN]
    assert 'high = repair_swap16(v) << 16;' in made[repair.STAGED]
    assert made[repair.STAGED].count(' / 4') == 2 and 'repair_word' not in made[repair.STAGED]


def test_a_signed_word_or_a_rewritten_word_is_left_alone():
    signed = SOURCE.replace('    u32 word;', '    s32 word;')
    assert repair.PLAIN not in children(signed)
    rewritten = SOURCE.replace('    out[0] =', '    word = 0;\n    out[0] =')
    assert repair.PLAIN not in children(rewritten)


def test_a_halfword_swap_inside_arithmetic_keeps_its_signed_type():
    source = '''void f(u16 *p, s32 *out) {
    u16 half;

    half = p[0];
    out[0] = (((half & 0xFF) << 8) + (half >> 8)) - 0x100;
}
'''
    assert children(source, 'f') == {}


def test_an_unsigned_dividend_is_not_moved_into_a_signed_word():
    source = '''void f(u32 a, u32 b, u32 *out) {
    out[0] = (a + 1) / 4;
    out[1] = (b + 1) / 4;
}
'''
    assert children(source, 'f') == {}
