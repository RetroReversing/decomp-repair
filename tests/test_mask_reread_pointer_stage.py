"""mask_reread_pointer_stage: a cell mask temporary read twice from its table, the element pointer staged."""

from decomprepair import mask_reread_pointer_stage as m

SOURCE = """typedef unsigned short u16;
typedef int s32;
static int both(s32 a, s32 b) { return a & b; }
void f(char *mesh, u16 lo, u16 hi, int n)
{
  int i;
  s32 idx;
  u16 mask;
  s32 tri;
  i = 0;
  do { idx = i & 0xFFFF; mask = *((u16 *) ((idx * 2) + (*((s32 *) (mesh + 0x38))))); tri = (*((s32 *) (mesh + 0x3C))) + (idx * 6); if ((lo & mask) && both(hi, mask)) { *((u16 *) tri) = 0; } i++; } while (i < n);
}
"""


def test_both_edits_come_as_one_child():
    fam, text = m.variants(SOURCE, 'f')[0]
    assert fam == m.FAMILY
    load = '(*((u16 *) ((idx * 2) + (*((s32 *) (mesh + 0x38))))))'
    assert 'tri = *((s32 *) (mesh + 0x3C)); tri += idx * 6;' in text
    assert 'if ((%s & lo) && (%s & hi)) {' % (load, load) in text
    assert 'mask = ' not in text


def test_a_mask_read_elsewhere_is_left_alone():
    again = SOURCE.replace('*((u16 *) tri) = 0;', '*((u16 *) tri) = mask;')
    assert m.variants(again, 'f') == []


def test_the_pointer_sum_before_the_mask_is_found_too():
    swapped = SOURCE.replace(
        'mask = *((u16 *) ((idx * 2) + (*((s32 *) (mesh + 0x38))))); tri = (*((s32 *) (mesh + 0x3C))) + (idx * 6);',
        'tri = (*((s32 *) (mesh + 0x3C))) + (idx * 6); mask = *((u16 *) ((idx * 2) + (*((s32 *) (mesh + 0x38)))));')
    fam, text = m.variants(swapped, 'f')[0]
    assert 'tri += idx * 6;' in text and 'mask = ' not in text
