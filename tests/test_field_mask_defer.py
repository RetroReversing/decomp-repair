"""Fields pulled out of one word written shifts first, masks after."""
from decomprepair import field_mask_defer as m

SOURCE = '''void f(u8 *cmd, u32 *out)
{
    s32 a;
    s32 b;
    s32 r;
    s32 v;
    v = cmd[2] + (cmd[1] << 8);
    {
        s32 w = v;
        a = ((u32)v >> 5) & 0x1F;
        v = (v >> 10) & 0x1F;
        r = w & 0x1F;
    }
    out[0] = (a << 9) | (v << 1) | r;
}
'''


def test_shifts_first_then_masks():
    # An SN GCC 2.8.1 model loader's triangle arms: 775 -> 535 under -mfp32 with every block written this way.
    found = m.variants(SOURCE, 'f')
    assert found and {family for family, _ in found} == {'field_mask_defer'}
    whole = found[0][1]
    assert ('        a = (u32)v >> 5;\n        v = v >> 10;\n        a &= 0x1F;\n        v &= 0x1F;\n'
            '        r = w & 0x1F;\n') in whole
    singles = [text for _, text in found[1:]]
    assert any('a = (u32)v >> 5;\n        v = (v >> 10) & 0x1F;\n        r = w & 0x1F;\n        a &= 0x1F;' in t
               for t in singles)


def test_left_alone_otherwise():
    # a later statement reads the unmasked field, or nothing is a masked shift
    assert m.variants(SOURCE.replace('r = w & 0x1F;', 'r = a + w;').replace('v = (v >> 10) & 0x1F;', 'v = a >> 1;'),
                      'f') == []
    assert m.variants(SOURCE.replace('((u32)v >> 5) & 0x1F', 'v + 1').replace('(v >> 10) & 0x1F', 'v * 3'), 'f') == []
