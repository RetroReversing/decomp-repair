"""A temporary stored into a local array's element, read back later as that element."""
from decomprepair import frame_slot_read_back as r

# The shape of an N64 projection routine (SN GCC 2.7.2 -O1), synthetic names.
SOURCE = '''extern s32 G;

s32 f(s16 *in, s16 *out) {
    s32 sp0[3];
    s32 t;
    s32 acc;

    acc = in[0] * in[1];
    t = acc >> 0xC;
    sp0[0] = t;
    sp0[1] = (in[2] * in[3]) >> 0xC;
    out[0] = (s16) ((G * t) / sp0[1]);
    out[1] = (s16) (t + 1);
    return sp0[1];
}
'''


def test_each_later_read_and_all_of_them():
    kids = r.variants(SOURCE, 'f')
    assert [family for family, _ in kids] == ['frame_slot_read_back'] * 3
    first, second, both = (out for _, out in kids)
    assert 'out[0] = (s16) ((G * sp0[0]) / sp0[1]);' in first and 'out[1] = (s16) (t + 1);' in first
    assert 'out[1] = (s16) (sp0[0] + 1);' in second and '(G * t)' in second
    assert '(G * sp0[0])' in both and '(sp0[0] + 1)' in both
    assert all('    sp0[0] = t;\n' in out and '    t = acc >> 0xC;\n' in out for _, out in kids)


def test_left_alone_when_the_temporary_or_the_slot_changes():
    assert r.variants(SOURCE.replace('    sp0[1] = (in', '    t = 4;\n    sp0[1] = (in'), 'f') == []
    assert r.variants(SOURCE.replace('    sp0[1] = (in', '    sp0[0] = 4;\n    sp0[1] = (in'), 'f') == []
    assert r.variants(SOURCE.replace('s32 sp0[3];', 's32 *sp0;'), 'f') == []
    assert r.variants(SOURCE.replace('    out[0] = (s16) ((G * t) / sp0[1]);\n    out[1] = (s16) (t + 1);\n', ''),
                      'f') == []
