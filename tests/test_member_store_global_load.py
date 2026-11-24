"""A cast-pointer store before the next read of a plain global, written as a structure member store."""
from decomprepair.member_store_global_load import FAMILY, variants

# A projectile update's bounce (KMC GCC 2.7.2, N64): three stores through the record pointer, then a test of a global.
TEXT = '''extern void *gTargetObject;
extern s32 gTable[4];
void f(void *p, f32 a, f32 b, f32 c)
{
  (*(f32 *)((char *)(p) + 0)) = a;
  (*(f32 *)((char *)(p) + 4)) = (f32) b;
  (*(f32 *)((char *)(p) + 8)) = (f32) c;
  if (gTargetObject != NULL) {
    g(p);
  }
}
'''


def _children(text, header=''):
    return [src for fam, src in variants(text, 'f', header) if fam == FAMILY]


def test_the_store_alone_and_its_run():
    last = TEXT.replace('(*(f32 *)((char *)(p) + 8)) = (f32) c;', '((struct { u8 pad[8]; f32 v; } *)(p))->v = (f32) c;')
    run = last.replace('(*(f32 *)((char *)(p) + 0)) = a;', '((struct { f32 v; } *)(p))->v = a;') \
              .replace('(*(f32 *)((char *)(p) + 4)) = (f32) b;', '((struct { u8 pad[4]; f32 v; } *)(p))->v = (f32) b;')
    assert _children(TEXT) == [last, run]


def test_a_global_from_the_header_counts():
    text = TEXT.replace('extern void *gTargetObject;\n', '')
    assert len(_children(text, 'extern void *gTargetObject;\n')) == 2


def test_no_global_read_next_is_left_alone():
    assert _children(TEXT.replace('if (gTargetObject != NULL)', 'if (p != NULL)')) == []


def test_an_array_or_a_call_is_not_a_scalar_global():
    assert _children(TEXT.replace('if (gTargetObject != NULL)', 'if (gTable[0] != 0)')) == []
    text = TEXT.replace('if (gTargetObject != NULL)', 'if (gTargetObject() != NULL)')
    assert _children(text) == []


def test_sites_sharing_stores_are_rewritten_once_together():
    text = TEXT.replace('  if (gTargetObject != NULL) {', '  q = gTargetObject;\n  (*(f32 *)((char *)(p) + 12)) = a;\n'
                        '  if (gTargetObject != NULL) {')
    together = _children(text)[-1]
    assert together.count('struct {') == 4 and '(char *)(p)' not in together
