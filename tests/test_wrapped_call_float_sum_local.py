"""A float sum passed to a wrapped call: an f32 local set before the wrappers, at the depth and one less, both orders."""
from decomprepair.wrapped_call_float_sum_local import FAMILY, REPAIR, variants

SAVED = '''void f(f32 cx, s16 x)
{
    switch (x) {
    case 2:
        do { do { do { g(p, (u16) (u32) (x + (2.0f * cx - 16.0f)), 3); } while (0); } while (0); } while (0);
        break;
    }
}
'''


def _squash(text):
    return ' '.join(text.split())


def _children(source):
    return [_squash(src) for fam, src in variants(source, 'f') if fam == FAMILY]


def test_the_sum_moves_into_a_local_before_the_wrappers():
    children = _children(SAVED)
    assert ('{ f32 sx = x + (2.0f * cx - 16.0f); do { do { do { g(p, (u16) (u32) sx, 3); } while (0); } while (0); }'
            ' while (0); }') in children[0]


def test_the_measured_child_swaps_the_operands_and_drops_one_wrapper():
    assert any('{ f32 sx = (2.0f * cx - 16.0f) + x; do { do { g(p, (u16) (u32) sx, 3); } while (0); } while (0); }'
               in c for c in _children(SAVED))


def test_no_child_without_a_float_sum_or_a_wrapper():
    assert _children(SAVED.replace('2.0f * cx - 16.0f', 'cx')) == []
    assert _children(SAVED.replace('do { do { do { ', '').replace(' } while (0); } while (0); } while (0);', '')) == []


def test_it_declares_itself():
    assert REPAIR['families'] == (FAMILY,) and REPAIR['variants'] is variants
