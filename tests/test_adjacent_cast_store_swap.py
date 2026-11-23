"""Two neighbouring stores through casts of one base, written in the other order."""
import re

from decomprepair.adjacent_cast_store_swap import variants

CODE = '''void f(char *p, char *q)
{
  *((s16 *) inline_fn2((char *) p, 0x178)) = 0;
  *((u16 *) (((char *) p) - (-0x17A))) = (u16) (*((u16 *) inline_fn2((char *) q, 0x24)));
  g(p);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_a_constant_store_and_a_loaded_value_store_are_swapped():
    [(family, child)] = variants(CODE, 'f')
    assert family == 'adjacent_cast_store_swap'
    text = squash(child)
    assert text.index('- (-0x17A)') < text.index('0x178')
    assert text.count('0x178') == 1 and text.count('0x24') == 1


def test_overlapping_stores_and_calls_stay_in_order():
    assert variants(CODE.replace('0x17A', '0x179'), 'f') == []
    assert variants(CODE.replace('(u16) (*((u16 *) inline_fn2((char *) q, 0x24)))', 'h(q)'), 'f') == []


def test_a_value_read_through_the_same_base_inside_the_other_store_is_kept_in_order():
    code = CODE.replace('inline_fn2((char *) q, 0x24)', 'inline_fn2((char *) p, 0x178)')
    assert variants(code, 'f') == []


def test_a_gap_between_the_stores_is_not_a_neighbour():
    assert variants(CODE.replace('  *((u16 *) (((char', '  k = 1;\n  *((u16 *) (((char'), 'f') == []


def test_two_record_member_stores_of_one_base_swap_too():
    """`frame_slot_alias_split` writes the pointer stores as members of one-field records; they swap like the casts."""
    code = """void f(void *rec, s32 *q) {
    s32 n;

    n = q[0];
    ((__repair_rec_64_u16 *) rec)->f = (u16) n;
    ((__repair_rec_66_u16 *) rec)->f = (u16) (*((u16 *) (((char *) q) + 4)));
}
"""
    flat = [re.sub(r'\s+', ' ', text) for _, text in variants(code, 'f')]
    assert len(flat) == 1
    assert flat[0].index('__repair_rec_66_u16 *) rec)->f') < flat[0].index('__repair_rec_64_u16 *) rec)->f')
    overlap = code.replace('__repair_rec_66_u16', '__repair_rec_64_u16')
    assert variants(overlap, 'f') == []
    called = code.replace('(u16) n;', '(u16) call(n);')
    assert variants(called, 'f') == []
