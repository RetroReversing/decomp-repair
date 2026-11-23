"""A parameter's cast and the local holding it, written as one copy kept in a dead loop counter."""
from decomprepair import dead_counter_cast_copy as p
from decomprepair import registry

SOURCE = '''typedef unsigned char u8;
typedef short s16;
typedef int s32;
inline static int twice(s16 a) { return a * 2; }

s32 slot(u8 *object, u8 action, s32 value)
{
    s16 i;
    s32 id;
    for (i = 1; i < 30; i++) {
        if (object[0x139 + twice(i)] == ((u8) action)) {
            return 1;
        }
    }
    id = (u8) action;
    if (((u32) id) < 31) {
        *((u16 *) ((object + 0x138) + twice(((u8) action)))) = id | (((u8) value) << 8);
    }
    return 0;
}
'''


def test_the_cast_and_the_local_share_the_dead_counter():
    children = p.variants(SOURCE, 'slot')
    assert [family for family, _ in children] == [p.FAMILY]
    text = children[0][1]
    assert 'i = (u8) action; *((u16 *) ((object + 0x138) + twice(i))) = i | (((u8) value) << 8);' in text
    assert text.count('id = (u8) action;') == 1


def test_a_counter_used_after_the_statement_is_left_alone():
    assert p.variants(SOURCE.replace('    return 0;\n}', '    return i;\n}'), 'slot') == []


def test_a_local_that_changes_between_is_left_alone():
    assert p.variants(SOURCE.replace('if (((u32) id) < 31) {', 'id = 3;\n    if (((u32) id) < 31) {'), 'slot') == []


def test_an_assignment_in_a_closed_block_does_not_count():
    source = SOURCE.replace('    id = (u8) action;\n', '    if (value) { id = (u8) action; }\n')
    assert p.variants(source, 'slot') == []


def test_it_declares_itself_to_the_registry():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'dead_counter_cast_copy')) == []
