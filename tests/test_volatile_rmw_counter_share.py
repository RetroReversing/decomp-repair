"""volatile_rmw_counter_share: the counter read in the masked value's local, before the volatile store (60 -> 30)."""
from decomprepair import volatile_rmw_counter_share as s

SOURCE = '''typedef struct { u8 pad[16]; u32 color; } Item;
extern u16 gTick;
extern u16 gAlpha;

void pulse(Item *current) {
    *((volatile u32 *) (&current->color)) = (current->color & (~255)) | (gAlpha << 3);
    gTick++;
}
'''


def test_the_counter_is_read_into_the_masked_locals_name_before_the_store():
    ((family, text),) = s.variants(SOURCE, 'pulse')
    assert family == s.FAMILY
    body = text.split('void pulse')[1]
    assert 'rmw_m = current->color & (~255);' in body and 'rmw_t = gAlpha << 3;' in body
    order = [body.index(x) for x in ('rmw_cur = rmw_m | rmw_t;', 'rmw_m = gTick;', '*((volatile u32 *) (&current->color)) = rmw_cur;',
                                     'gTick = rmw_m + 1;')]
    assert order == sorted(order)
    assert 'u32 rmw_m;' in body


def test_a_plus_equals_one_counts_and_other_shapes_decline():
    assert s.variants(SOURCE.replace('gTick++;', 'gTick += 1;'), 'pulse')
    assert s.variants(SOURCE.replace('gTick++;', 'gTick += 2;'), 'pulse') == []
    assert s.variants(SOURCE.replace('(current->color & (~255))', '(current->pad & (~255))'), 'pulse') == []
    assert s.variants(SOURCE.replace('    gTick++;', '    while (gTick) gTick++;'), 'pulse') == []


def test_the_module_declares_itself_for_the_registry():
    assert s.REPAIR['variants'] is s.variants and s.REPAIR['families'] == s.FAMILIES
