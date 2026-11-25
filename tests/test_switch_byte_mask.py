"""switch_byte_mask: a switch on a byte kept in a wider local, with or without the mask."""
from decomprepair import registry
from decomprepair import switch_byte_mask as mask

SOURCE = '''void put(s32);
s32 f(u8 *p) {
    s32 ch;

    ch = *p;
    while (ch != 0) {
        switch (ch) {
        case 0xA:
            put(1);
            break;
        default:
            put(ch);
            break;
        }
        p++;
        ch = *p;
    }
    return 0;
}
'''


def test_the_mask_is_added_to_a_switch_on_a_byte_local():
    out = mask.variants(SOURCE, 'f')
    assert [family for family, _ in out] == [mask.FAMILY]
    assert out[0][1] == SOURCE.replace('switch (ch)', 'switch (ch & 0xFF)')


def test_and_dropped_from_one_that_has_it():
    source = SOURCE.replace('switch (ch)', 'switch (ch & 0xFF)')
    assert [child for _, child in mask.variants(source, 'f')] == [SOURCE]


def test_a_local_that_can_be_wider_than_a_byte_is_left_alone():
    assert mask.variants(SOURCE.replace('ch = *p;\n    while', 'ch = *p + n;\n    while'), 'f') == []
    assert mask.variants(SOURCE.replace('u8 *p', 's32 *p'), 'f') == []
    assert mask.variants(SOURCE.replace('        ch = *p;\n', '        ch = ch + 1;\n'), 'f') == []
    assert mask.variants(SOURCE.replace('        ch = *p;\n', '        ch++;\n'), 'f') == []


def test_it_is_declared_for_the_registry():
    item = registry.get('switch_byte_mask')
    assert mask.FAMILY in item.families and not registry.problems(item)
