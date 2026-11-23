from decomprepair import registry
from decomprepair.shared_index_byte_copy import FAMILY, variants

SOURCE = """typedef struct { u8 map[0x80]; u8 map2[0x80]; s32 slot[2]; } Bank;
void pick(Bank *p, s32 a, u8 chan) {
    if (a & 0x80) {
        s32 idx = a & 0x7F;
        if (chan != 9) {
            u8 m = p->map[idx];
            if (m != 0xFF) {
                p->slot[0] = m;
            }
        } else {
            u8 m = p->map2[idx];
            if (m != 0xFF) {
                p->slot[1] = m;
            }
        }
    }
}
"""


def test_the_first_arm_reads_a_byte_copy_inside_two_scopes():
    children = [c for f, c in variants(SOURCE, 'pick') if f == FAMILY]
    assert len(children) == 4
    child = children[0]
    assert 'u16 idx = a & 0x7F;' in child
    assert 'u8 idx_copy = idx;' in child
    assert 'u8 m;\n            do { do { m = p->map[idx_copy]; } while (0); } while (0);' in child
    assert 'u8 m = p->map2[idx];' in child
    assert 'do { do { do {' in children[1] and 'do { do { do {' not in child
    assert 'm = p->map2[idx_copy]' in children[2] and 'p->map[idx];' in children[2]


def test_a_split_declaration_gets_the_copy_beside_it():
    source = SOURCE.replace('        s32 idx = a & 0x7F;', '        idx = a & 0x7F;').replace(
        '    if (a & 0x80) {', '    s32 idx;\n    if (a & 0x80) {')
    child = variants(source, 'pick')[0][1]
    assert 'u16 idx;' in child and 'u8 idx_copy;' in child
    assert 'idx_copy = idx;' in child and 'm = p->map[idx_copy];' in child


def test_a_wide_mask_one_read_or_three_reads_is_declined():
    assert variants(SOURCE.replace('a & 0x7F', 'a & 0x7FF'), 'pick') == []
    assert variants(SOURCE.replace('p->map2[idx]', 'p->map2[0]'), 'pick') == []
    assert variants(SOURCE.replace('p->slot[1] = m;', 'p->slot[1] = idx;'), 'pick') == []


def test_reads_in_one_arm_or_a_changed_index_are_declined():
    assert variants(SOURCE.replace('} else {', '}\n        if (chan == 9) {'), 'pick') == []
    assert variants(SOURCE.replace('p->slot[0] = m;', 'idx = 3;'), 'pick') == []


def test_a_narrow_index_is_kept_as_it_is():
    child = variants(SOURCE.replace('s32 idx', 'u8 idx'), 'pick')[0][1]
    assert 'u8 idx = a & 0x7F;' in child and 'u8 idx_copy = idx;' in child


def test_registry_declares_the_family():
    assert any(FAMILY in repair.families for repair in registry.declared())
