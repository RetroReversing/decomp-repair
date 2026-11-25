"""A wide constant held in the local an earlier test read through, with the stores pinned (190 -> 70 on a 72-insn update)."""
from decomprepair.constant_compare_temp_reuse import FAMILY, REPAIR, variants

SOURCE = """s32 update(u8 *obj) {
    u8 *p;
    f32 f;

    if (*(s32 *) (D_800B3964 + 0x7C) != 4) {
        return 0;
    }
    p = D_800B3960;
    f = *(f32 *) (obj + 0xC) - 4500.0f;
    *(u8 **) (p + 0xA8) = obj;
    *(f32 *) (p + 0xC) = f;
    *(s32 *) (obj + 0x10) = *(s32 *) (p + 0x10) + 0x8000;
    return 0;
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'update') if family == FAMILY]


def test_reuse_then_reuse_with_pins():
    found = children()
    assert len(found) == 2
    reuse, pinned = found
    assert '    s32 k;' in reuse
    assert '    k = *(s32 *) (D_800B3964 + 0x7C);\n    if (k != 4) {' in reuse
    assert '    k = 0x8000;\n    *(s32 *) (obj + 0x10) = *(s32 *) (p + 0x10) + k;' in reuse
    assert 'volatile' not in reuse
    assert '*(u8 * volatile *) (p + 0xA8) = obj;' in pinned
    assert '*(volatile f32 *) (p + 0xC) = f;' in pinned
    assert '= *(volatile s32 *) (p + 0x10) + k;' in pinned
    assert 'f = *(f32 *) (obj + 0xC)' in pinned


def test_a_small_constant_is_an_addiu():
    assert children(SOURCE.replace('+ 0x8000;', '+ 0x7FFF;')) == []


def test_a_test_that_calls_is_not_reused():
    source = SOURCE.replace('if (*(s32 *) (D_800B3964 + 0x7C) != 4)', 'if (get(D_800B3964) != 4)')
    assert children(source) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and REPAIR['archs'] == ('mips',)
