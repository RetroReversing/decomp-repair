from decomprepair.byte_pointer_sum_staged import FAMILY, variants
from decomprepair.registry import declared

# the saved best of a KMC GCC 2.7.2 -O1 table minimum (an N64 game), shortened; its twin had the same line
SOURCE = """s16 f(void *arg0, s16 arg1) {
    void *temp_a0;
    void *temp_a0_2;
    temp_a0 = arg0 + 0xC;
    { void *__fence_temp_a0; do { __fence_temp_a0 = temp_a0; } while (0); temp_a0_2 = (arg1 * 0x18) + __fence_temp_a0; }
    return *(s16 *)((s8 *)temp_a0_2 + 2);
}
"""
STAGED = ('{ s32 __repair_sum; __repair_sum = (arg1 * 0x18) + (s32) __fence_temp_a0; '
          'temp_a0_2 = (void *) __repair_sum; }')


def test_the_sum_is_staged_as_an_integer_with_the_index_first():
    texts = [text for family, text in variants(SOURCE, 'f') if family == FAMILY]
    assert texts[0].count(STAGED) == 1
    assert 'temp_a0_2 = (void *) ((arg1 * 0x18) + (s32) __fence_temp_a0);' in texts[1]
    # a constant offset is an addiu: not offered
    assert not any('(s32) arg0' in t for t in texts)
    swapped = SOURCE.replace('(arg1 * 0x18) + __fence_temp_a0', '__fence_temp_a0 + (arg1 * 0x18)')
    assert any(STAGED in text for _, text in variants(swapped, 'f'))


def test_word_pointers_calls_and_integer_destinations_are_left_alone():
    assert variants(SOURCE.replace('void *__fence_temp_a0', 's32 *__fence_temp_a0'), 'f') == []
    assert variants(SOURCE.replace('(arg1 * 0x18)', 'g(arg1)'), 'f') == []
    assert variants(SOURCE.replace('    void *temp_a0_2;', '    s32 temp_a0_2;'), 'f') == []
    assert any(FAMILY in r.families for r in declared())
