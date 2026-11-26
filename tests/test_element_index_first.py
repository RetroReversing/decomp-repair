"""element_index_first: a global array's element written with the scaled index first.

Synthetic shape of a 182-instruction SN64 GCC 2.8.1 allocator (145 -> 120): `D[i] = (s32) (buf + size);` before a call
took the target's base and index registers as `*(s32 *)((i << 2) + (u8 *)D)`."""
from decomprepair import element_index_first as s

SOURCE = '''extern s32 gEnds[];
extern u16 gHalves[];
extern u8 gBytes[];
s32 put(s32, u8 *);

s32 grow(s32 idx, u8 *buf, s32 size) {
    s32 *p;
    gEnds[idx] = (s32)(buf + size);
    gHalves[idx + 1] = 3;
    gBytes[idx] = 1;
    p = &gEnds[idx];
    return put(idx, buf + size) + gEnds[get(idx)];
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'grow') if family == s.FAMILY]


def test_the_shift_first_and_the_product_first():
    texts = _texts()
    assert any('(*(s32 *)((idx << 2) + (u8 *)gEnds)) = (s32)(buf + size);' in t for t in texts)
    assert any('(*(s32 *)((idx * 4) + (u8 *)gEnds)) = (s32)(buf + size);' in t for t in texts)
    assert any('(*(u16 *)(((idx + 1) << 1) + (u8 *)gHalves)) = 3;' in t for t in texts)
    assert any('(*(u8 *)(idx + (u8 *)gBytes)) = 1;' in t for t in texts)


def test_a_compound_index_is_parenthesised_before_it_is_scaled():
    assert any('(*(u16 *)(((idx + 1) * 2) + (u8 *)gHalves)) = 3;' in t for t in _texts())


def test_addresses_and_side_effect_indexes_are_left_alone():
    texts = _texts()
    assert all('p = &gEnds[idx];' in t for t in texts)
    assert all('gEnds[get(idx)]' in t for t in texts)


def test_locals_and_unknown_arrays_are_left_alone():
    assert _texts(SOURCE.replace('extern s32 gEnds[];\nextern u16 gHalves[];\nextern u8 gBytes[];\n', '')) == []
