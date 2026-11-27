"""A length clipped to a far edge, written as taking the overshoot off it."""
from decomprepair import clamp_overshoot_subtract as p
from decomprepair import registry

SOURCE = '''void clip(short x, short y, short w, short h, short right, short bottom)
{
    if (x + w > right) {
        w = right - x;
    }
    if (bottom < (short)y + h)
        h = bottom - y;
    draw(x, y, w, h);
}
'''


def test_both_edges_then_each():
    children = p.variants(SOURCE, 'clip')
    assert [family for family, _ in children] == [p.FAMILY] * 3
    assert 'w -= x + w - right;' in children[0][1] and 'h -= y + h - bottom;' in children[0][1]
    assert 'w -= x + w - right;' in children[1][1] and 'h = bottom - y;' in children[1][1]
    assert 'h -= y + h - bottom;' in children[2][1] and 'w = right - x;' in children[2][1]


def test_only_under_the_matching_test_and_it_is_registered():
    assert p.variants(SOURCE.replace('x + w > right', 'x > right').replace('bottom < (short)y + h', 'h'), 'clip') == []
    assert p.variants(SOURCE.replace('w = right - x;', 'w = right - y;').replace('h = bottom - y;', ';'), 'clip') == []
    assert any(p.FAMILY in repair.families for repair in registry.declared())
