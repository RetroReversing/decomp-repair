"""A cast on a macro argument moved into the macro's non-packing uses."""
from decomprepair.macro_cast_argument_move import FAMILY, variants

SAVED = '''#define _SHIFTL(v, s, w) ((u32)(((u32)(v) & ((0x01 << (w)) - 1)) << (s)))
#define ADJ(v, d) (((d) < 0) ? (v) : 0)
#define RECT(pkt, xl, dsdx, dtdy) \\
{ Gfx *_g = (Gfx *)(pkt); \\
  _g->w0 = _SHIFTL(ADJ(((xl) * (dsdx)) >> 7, dsdx), 16, 16); \\
  _g->w1 = (_SHIFTL(dsdx, 16, 16) | _SHIFTL(dtdy, 0, 16)); }
void f(Gfx *p, s32 x, s32 a, s32 b)
{
  RECT(p, x, (s16) a, (s16) b);
  RECT(p, x + 1, (s16) a, (s16) b);
}
'''


def _children(source):
    return [src for fam, src in variants(source, 'f') if fam == FAMILY]


def test_the_cast_moves_from_every_call_into_the_other_uses_of_the_parameter():
    out = _children(SAVED)
    assert len(out) == 1  # dtdy is only packed raw: nothing else of it to cast
    first = out[0]
    assert 'RECT(p, x, a, (s16) b);' in first and 'RECT(p, x + 1, a, (s16) b);' in first
    assert '_SHIFTL(dsdx, 16, 16)' in first
    assert 'ADJ(((xl) * (((s16)(dsdx)))) >> 7, ((s16)(dsdx)))' in first.replace('  ', ' ')


def test_a_call_that_passes_the_argument_without_the_cast_leaves_the_macro_alone():
    source = SAVED.replace('RECT(p, x + 1, (s16) a, (s16) b);', 'RECT(p, x + 1, a, (s16) b);')
    assert [c for c in _children(source) if '((s16)(dsdx))' in c] == []


def test_a_parameter_never_packed_raw_gives_no_child():
    assert _children(SAVED.replace('_SHIFTL(dsdx, 16, 16)', '_SHIFTL(1, 16, 16)')) == []


def test_every_macro_and_parameter_together_is_one_more_child():
    from decomprepair.macro_cast_argument_move import FAMILY_ALL
    both = SAVED.replace('_SHIFTL(dtdy, 0, 16)', '_SHIFTL(dtdy, 0, 16) | ADJ(((xl) * (dtdy)) >> 7, dtdy)')
    alls = [c for fam, c in variants(both, 'f') if fam == FAMILY_ALL]
    assert len(alls) == 1
    assert '((s16)(dsdx))' in alls[0] and '((s16)(dtdy))' in alls[0]
    assert 'RECT(p, x, a, b);' in alls[0] and 'RECT(p, x + 1, a, b);' in alls[0]
