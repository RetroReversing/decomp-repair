from decomprepair.narrow_result_unify import FAMILY_BOTH, FAMILY_INLINE, FAMILY_SWAP, FAMILY_UNIFY, variants

CLAMP = """
void step(s32 delta) {
 s32 wide, mask; s16 level; u32 high, word; u16 low; void *rec;
 rec = *(void **)((char *)state + 0x18);
 wide = *(u8 *)((char *)rec + 0x10);
 word = *(u32 *)((char *)rec + 0x14);
 low = word;
 high = word >> 16;
 play(0xE8);
 level = wide + delta; wide = level; mask = low & 0xFFFF;
 if (mask < level) wide = high; else if (level < (s32)high) wide = low;
 level = wide;
 *(u8 *)((char *)rec + 0x10) = level;
 use(level);
}
"""


def children(source, family):
    return [text for found, text in variants(source, 'step') if found == family]


def test_the_wide_carrier_is_folded_into_the_narrow_local():
    [text] = children(CLAMP, FAMILY_UNIFY)
    assert 'wide' not in text.replace('s32 mask', '')
    assert 'level = *(u8 *)' in text and 'level = level + delta;' in text
    assert 'if (mask < level) level = high; else if (level < (s32)high) level = low;' in text
    assert 'level = wide' not in text and 'wide =' not in text


def test_the_whole_chain_is_one_child_with_the_mask_written_into_the_swapped_compare():
    [text] = children(CLAMP, FAMILY_BOTH)
    assert 'if (level > (low & 0xFFFF)) level = high;' in text
    assert 'mask' not in text


def test_a_compare_of_two_plain_operands_is_offered_the_other_way_round():
    swapped = children(CLAMP, FAMILY_SWAP)
    assert any('if (level > mask)' in text for text in swapped)
    [inline] = [t for t in children(CLAMP, FAMILY_INLINE) if 'level > (low & 0xFFFF)' in t]
    assert 'mask' not in inline


def test_a_wide_local_read_elsewhere_is_not_folded():
    assert not children(CLAMP.replace(' use(level);', ' use(wide);'), FAMILY_UNIFY)


def test_a_wide_local_whose_value_is_compared_is_not_folded():
    source = CLAMP.replace('level = wide;\n', 'level = wide; if (wide > 5) go();\n')
    assert not children(source, FAMILY_UNIFY)


def test_a_mask_set_by_a_call_or_changed_before_the_compare_stays_put():
    assert not children(CLAMP.replace('mask = low & 0xFFFF;', 'mask = peek(low);'), FAMILY_INLINE)
    assert not children(CLAMP.replace('mask = low & 0xFFFF;', 'mask = low & 0xFFFF; low = 3;'), FAMILY_INLINE)


def test_compound_conditions_are_left_alone():
    source = CLAMP.replace('if (mask < level)', 'if (mask < level && go())')
    assert not [t for t in children(source, FAMILY_SWAP) if 'level > mask &&' in t]

