from decomprepair import loop_tail_update_order_repairs as repair

SOURCE = '''void f(int n) {
    s32 i;
    s32 offset;
    i = 0;
    offset = 0;
    do {
        *(s32 *)(D_a + offset) = 0;
        i += 1;
        offset += 0x1A0;
    } while (i < 0x20);
    i = 0;
    offset = 0;
    do {
        *(s32 *)(D_b + offset) = 0;
        i += 1;
        offset += 0x28;
    } while (i < 0x20);
}
'''


def test_swaps_each_loop_and_both():
    found = [c for _, c in repair.variants(SOURCE, 'f')]
    assert len(found) == 3
    both = found[-1]
    assert both.count('offset += 0x1A0;\n        i += 1;') == 1
    assert both.count('offset += 0x28;\n        i += 1;') == 1
    assert found[0].count('i += 1;\n        offset += 0x28;') == 1


def test_leaves_other_tails_alone():
    assert not repair.variants('void f(void) { do { g(); i += 1; } while (i < 3); }', 'f')
    assert not repair.variants('void f(void) { do { i += 1; i += 2; } while (i < 3); }', 'f')
