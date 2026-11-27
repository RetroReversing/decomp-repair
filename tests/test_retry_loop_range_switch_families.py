"""Locals read through a width mask become the narrow type; two-arm sums are added in place."""
from decomprepair import (
    arm_result_into_addend,
    guarded_range_switch,
    guarded_retry_loop,
    masked_read_local_narrow,
    registry,
    unsigned_mask_modulo,
)

SOURCE = '''void spawn(Obj *obj) {
    u32 side;
    s32 span;
    s32 off;
    s16 result;
    s32 tries;

    side = roll() >> 13;
    if (flags[side & 0xFFFF] == 0) {
        side = (side + 1) & 3;
        tries = flags[side];
    }
    use(side & 0xFFFF, tries);
    off = (span * roll()) / 32767;
    if (low < high) {
        result = off + low;
    } else {
        result = off + high;
    }
    obj->x = (s16) result;
}
'''


def test_the_masked_local_is_narrowed_and_the_masks_dropped():
    [(family, text)] = masked_read_local_narrow.variants(SOURCE, 'spawn')
    assert family == masked_read_local_narrow.FAMILY
    assert 'u16 side;' in text and 'flags[side]' in text and 'use(side, tries);' in text and '0xFFFF' not in text


def test_an_unmasked_read_of_a_full_word_keeps_the_local():
    assert masked_read_local_narrow.variants(SOURCE.replace('use(side & 0xFFFF, tries);',
                                                            'use(side & 0xFFFF, tries); keep(roll()); side = roll(); keep(side);'),
                                             'spawn') == []


def test_the_wrapping_step_becomes_two_statements():
    narrowed = masked_read_local_narrow.variants(SOURCE, 'spawn')[0][1]
    texts = [t for f, t in unsigned_mask_modulo.variants(narrowed, 'spawn') if f == unsigned_mask_modulo.WRAP_FAMILY]
    assert len(texts) == 1 and 'side++;\n        side %= 4;' in texts[0]


def test_the_arm_sum_is_added_into_the_value():
    [(family, text)] = arm_result_into_addend.variants(SOURCE, 'spawn')
    assert family == arm_result_into_addend.FAMILY
    assert 'off += low;' in text and 'off += high;' in text and 'obj->x = (s16) off;' in text


def test_a_value_read_again_is_not_overwritten():
    assert arm_result_into_addend.variants(SOURCE.replace('(s16) result;', '(s16) result;\n    keep(off);'), 'spawn') == []
    assert arm_result_into_addend.variants(SOURCE.replace('(s16) result', 'result'), 'spawn') == []


def test_they_are_registered():
    declared = {family for repair in registry.declared() for family in repair.families}
    assert {masked_read_local_narrow.FAMILY, arm_result_into_addend.FAMILY, unsigned_mask_modulo.WRAP_FAMILY} <= declared


RETRY = '''void pick(Obj *obj) {
    s32 n;
    u32 side;

    if (*(u8 *)(base + (side & 0xFFFF)) == 0) {
        n = 1;
loop_4:
        if (n != 4) {
            side = (side + 1) & 3;
            n += 1;
            if (*(u8 *)(side + base) != 0) {
                goto block_6;
            }
            goto loop_4;
        }
        fallback(obj);
        return;
    }
block_6:
    use(side);
}
'''


def test_the_guarded_retry_loop_becomes_a_while():
    [(family, text)] = guarded_retry_loop.variants(RETRY, 'pick')
    assert family == guarded_retry_loop.FAMILY
    assert '''    n = 0;
    while (*(u8 *)(base + (side & 0xFFFF)) == 0) {
        if (++n == 4) {
            fallback(obj);
            return;
        }
        side = (side + 1) & 3;
    }
    use(side);''' in text and 'goto' not in text
    assert any(guarded_retry_loop.FAMILY in repair.families for repair in registry.declared())


def test_a_counter_read_later_or_another_test_keeps_the_loop():
    assert guarded_retry_loop.variants(RETRY.replace('use(side);', 'use(side, n);'), 'pick') == []
    assert guarded_retry_loop.variants(RETRY.replace('(side + base)', '(side + other)'), 'pick') == []


def test_a_copy_of_the_narrowed_local_is_written_as_it():
    source = SOURCE.replace('    use(side & 0xFFFF, tries);', '    pick = side & 0xFFFF;\n    use(pick, tries);').replace(
        '    u32 side;\n', '    u32 side;\n    s32 pick;\n')
    [(_, inlined), (_, kept)] = masked_read_local_narrow.variants(source, 'spawn')
    assert 'pick' not in inlined and 'use(side, tries);' in inlined and 'pick = side;' in kept


TREES = '''void put(Obj *obj) {
    if ((obj->kind == 0x12F) && (side >= 0)) {
        if (side < 2) {
            x = table[side];
        } else {
            if (side < 4) {
                y = table[side];
            }
        }
    }
    if (side >= 0) {
        if (side < 2) {
            y = 1;
        } else if (side < 4) {
            x = 1;
        }
    }
}
'''


def test_guarded_range_trees_become_switches():
    texts = [text for _, text in guarded_range_switch.variants(TREES, 'put')]
    assert len(texts) == 3
    both = texts[-1]
    assert both.count('switch (side) {') == 2 and 'if (obj->kind == 0x12F) {' in both
    assert '''        case 2:
        case 3:
            x = 1;
            break;''' in both
    assert any(guarded_range_switch.FAMILY in repair.families for repair in registry.declared())
    assert len(guarded_range_switch.variants(TREES.replace('y = 1;', 'break;'), 'put')) == 1
