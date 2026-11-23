from decomprepair import registry
from decomprepair.volatile_step_index import FAMILY, variants

SOURCE = """
void walk(void *arg0, u8 *table, s32 *out) {
    s32 i;
    volatile s32 off3;
    volatile s32 off6;
    volatile s64 pad[2];
    s32 n;
    n = *(u16 *) ((u8 *) arg0 + 0x40); i = 0;
    if (n > 0) {
        off3 = 0; off6 = 0;
        do {
            if (*(u8 *) ((u8 *) arg0 + 0x48) & 4) {
                out[0] = *(s32 *) (table + off6);
            } else {
                out[1] = *(s32 *) (table + off3);
            }
            if (*(s32 *) ((u8 *) arg0 + 0x4C)) {
                off3 += 3;
                i += 1;
                off6 += 6;
            } else {
                off3 += 3;
                i += 1;
                off6 += 6;
            }
        } while (i < *(u16 *) ((u8 *) arg0 + 0x40));
    }
}
"""


def test_plain_cursors_one_guard_arm_and_the_counters_multiples_come_as_one_child():
    result = variants(SOURCE, 'walk')
    assert [family for family, _ in result] == [FAMILY]
    text = result[0][1]
    assert 'volatile' not in text and 'pad' not in text
    assert 'off3 +=' not in text and 'off6 +=' not in text and 'off3 = 0' not in text
    assert 'table + (i * 6)' in text and 'table + (i * 3)' in text
    assert text.count('i += 1;') == 1 and text.count('0x4C') == 0
    assert 'off3' not in text and 'off6' not in text


def test_a_volatile_that_is_really_memory_is_left_alone():
    # stored with something but zero, or its address taken: it is a memory object, not a cursor the compiler made
    taken = variants(SOURCE.replace('out[0] = *(s32 *) (table + off6);', 'out[0] = (s32) &off6;'), 'walk')
    assert len(taken) == 1 and 'volatile s32 off6;' in taken[0][1] and 'volatile s32 off3' not in taken[0][1]
    assert variants(SOURCE.replace('off3 = 0; off6 = 0;', 'off3 = 1; off6 = 1;'), 'walk') == []
    assert variants(SOURCE.replace('volatile ', ''), 'walk') == []
    assert variants(SOURCE.replace('off3 += 3;', 'off3 -= 3;').replace('off6 += 6;', 'off6 -= 6;'), 'walk') == []


def test_the_pad_is_kept_when_something_reads_it_and_nothing_is_offered_without_a_loop():
    kept = SOURCE.replace('out[1] =', 'out[2] = (s32) pad[0]; out[1] =')
    assert all('pad[0]' in text for _, text in variants(kept, 'walk'))
    assert variants(SOURCE.replace('do {', '{').replace('} while (i < *(u16 *) ((u8 *) arg0 + 0x40));', '}'), 'walk') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'volatile_step_index' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'volatile_step_index':
            assert registry.problems(repair) == []
