from decomprepair import recomputed_offset_for_loop as repair
from decomprepair import registry

SOURCE = """void f(s32 score) {
    s32 off;
    s32 off_2;
    u32 i;

    i = 0;
    if (mode != 0) {
        off = 0 * 4;
        do {
            if (*(s32 *)(off + first) < score) {
                i = 0xB;
            }
            i += 1;
            off = i * 4;
        } while (i < 0xAU);
    } else {
        off_2 = 0 * 4;
        do {
            g(*(s32 *)(off_2 + second));
            i += 1;
            off_2 = i * 4;
        } while (i < 0xAU);
    }
}
"""


def test_both_arms_become_loops_over_the_counter():
    children = [child for _, child in repair.variants(SOURCE, 'f')]
    assert len(children) == 3
    assert children[0].count('for (; i < 0xA; i++) {') == 2
    assert '*(s32 *)((i * 4) + first)' in children[0] and '*(s32 *)((i * 4) + second)' in children[0]
    assert 'off' not in children[0]


def test_a_counter_that_may_have_moved_is_left_alone():
    assert not repair.variants(SOURCE.replace('i = 0;\n    if', 'i = 0;\n    i += g(1);\n    if'), 'f')
    assert not repair.variants(SOURCE.replace('i = 0;\n    if', 'i = score;\n    if'), 'f')
    assert not repair.variants(SOURCE.replace('i += 1;', 'i += 2;'), 'f')


def test_it_is_registered():
    assert repair.FAMILY in str(registry.declared())
