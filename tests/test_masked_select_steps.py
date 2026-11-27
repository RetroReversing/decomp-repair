from decomprepair import masked_select_steps as m
from decomprepair import registry

SOURCE = '''extern u16 D_80100000[];
extern u8 D_80100100;

void f(u8 *gfx) {
    s32 i;
    u32 v;
    s32 c;

    for (i = 0; i < 7; i++) {
        v = D_80100000[D_80100100 + i];
        c = (u8) -((v & 0x1000) == 0) | 0x7F;
        draw(gfx, c, c, c);
    }
    c = (u8) -(i != 0xFF) | 0x60;
    draw(gfx, c, c, c);
}
'''


def children(family):
    return [text for name, text in m.variants(SOURCE, 'f') if name == family]


def test_select_written_step_by_step():
    every = children('masked_select_steps')[0]
    assert 'c = v;\n        c &= 0x1000;\n        c = c == 0;\n        c = -c;\n        c = (u8) c;\n        c |= 0x7F;' in every
    assert 'c = i ^ 0xFF;\n    c = c != 0;\n    c = -c;\n    c = (u8) c;\n    c |= 0x60;' in every


def test_narrow_reassign_after_a_load_in_a_call_loop_alone_and_with_the_steps():
    alone, both = children('loop_narrow_self_reassign')
    assert 'v = D_80100000[D_80100100 + i];\n        v = (u16) v;\n        c = (u8)' in alone
    assert 'v = (u16) v;' in both and 'c &= 0x1000;' in both


def test_nothing_without_a_wide_local_or_a_call():
    assert m.variants(SOURCE.replace('s32 c;', 'u8 c;').replace('u32 v;', 'u16 v;'), 'f') == []
    quiet = SOURCE.replace('draw(gfx, c, c, c);', 'gfx[0] = c;')
    assert not [n for n, _ in m.variants(quiet, 'f') if n == 'loop_narrow_self_reassign']


def test_declared():
    assert 'masked_select_steps' in [repair.module for repair in registry.declared()]
