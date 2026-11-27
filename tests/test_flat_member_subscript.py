from decomprepair import flat_member_subscript, registry

SOURCE = """typedef struct { u16 x, y; } Point;
extern Point table[];
extern s16 next;
void spawn(Point *out) {
    out->x = table[next].x;
    out->y = table[next].y;
}
"""


def children(source):
    return flat_member_subscript.variants(source, 'spawn')


def test_second_member_is_read_by_a_flat_subscript_held_in_a_local():
    child = dict(children(SOURCE))['member_flat_subscript']
    assert '    int flat_index0;\n' in child
    assert 'flat_index0 = next * 2 + 1;\n    out->y = ((u16 *) table)[flat_index0];' in child
    assert 'out->x = table[next].x;' in child


def test_a_written_sum_subscript_is_held_in_a_local():
    source = SOURCE.replace('table[next].y', 'words[next * 2 + 1]')
    child = dict(children(source))['subscript_sum_local']
    assert 'flat_index0 = next * 2 + 1;\n    out->y = words[flat_index0];' in child


def test_an_ored_byte_offset_is_written_as_an_element():
    source = SOURCE.replace('table[next].y', '*(u16 *)(((next * 4) | 2) + (s32)table)')
    child = dict(children(source))['or_offset_element']
    assert '(((next) * 2 + 1) * 2)' in child


def test_nothing_before_an_unbraced_arm_or_for_a_first_member():
    assert not children(SOURCE.replace('out->y = table[next].y;', 'if (next) out->y = table[0].x; else out->y = table[next].y;')
                        .replace('out->x = table[next].x;', ''))
    assert not children(SOURCE.replace('table[next].y', 'table[next].x'))


def test_declared_to_the_registry():
    assert any(entry.module == 'flat_member_subscript' for entry in registry.declared())
