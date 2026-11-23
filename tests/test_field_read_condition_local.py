"""A field read in an if condition kept in a local for the body (a player update, 4316 -> 4201)."""
from decomprepair.field_read_condition_local import FAMILY, REPAIR, variants

SOURCE = """void update(void *obj)
{
    s32 i;
    if ((gMode == 0) && (((Field_s16 *) (((char *) obj) + 0x7A))->v == 1)) {
        step(obj);
        if (gLevel == ((Field_s16 *) (((char *) obj) + 0x7A))->v) {
            fast(obj);
        }
    }
    if (((Field_s16 *) (((char *) obj) + 0x7A))->v >= 2) {
        slow(obj);
    }
}
"""


def children(source):
    return [text for family, text in variants(source, 'update') if family == FAMILY]


def test_the_first_read_assigns_and_the_body_reads_the_local():
    found = children(SOURCE)
    assert len(found) == 1
    child = found[0]
    assert '  s16 obj_field_7A;\n' in child
    assert '(obj_field_7A = ((Field_s16 *) (((char *) obj) + 0x7A))->v) == 1' in child
    assert 'if (gLevel == obj_field_7A) {' in child
    # the read after the `if` is a read again
    assert 'if (((Field_s16 *) (((char *) obj) + 0x7A))->v >= 2) {' in child


def test_a_store_to_the_field_leaves_it_alone():
    assert children(SOURCE.replace('step(obj);', '((Field_s16 *) (((char *) obj) + 0x7A))->v = 3;')) == []
    assert children(SOURCE.replace('step(obj);', '((Field_s16 *) (((char *) obj) + 0x7A))->v += 1;')) == []


def test_a_read_that_is_not_compared_or_has_no_read_in_its_body_is_left_alone():
    assert children(SOURCE.replace('(gMode == 0) && (((Field_s16 *) (((char *) obj) + 0x7A))->v == 1)', 'consume(((Field_s16 *) (((char *) obj) + 0x7A))->v)')) == []
    assert children(SOURCE.replace('if (gLevel == ((Field_s16 *) (((char *) obj) + 0x7A))->v) {', 'if (gLevel) {')) == []


def test_another_offset_or_base_is_another_field():
    other = SOURCE.replace('if (gLevel == ((Field_s16 *) (((char *) obj) + 0x7A))->v) {', 'if (gLevel == ((Field_s16 *) (((char *) obj) + 0x7C))->v) {')
    assert children(other) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']
