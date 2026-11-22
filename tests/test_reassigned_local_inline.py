"""A local's first value, read only by the test right after it, written into the test."""
from decomprepair import reassigned_local_inline as p
from decomprepair import registry

SOURCE = '''typedef unsigned char u8;
typedef int s32;
extern u8 table[];

s32 slot(u8 *object, u8 action)
{
    s32 id;
    if (object != 0) {
        id = (u8) action;
        if ((((u8) (action - 23)) < 2) | (id == 25)) {
            return 0;
        }
        object[1] = 2;
        id = (u8) action;
        object[id] = 1;
    }
    return 1;
}
'''


def first(source):
    """The child that removes the assignment before the test (the one that holds `object[1]` after the test)."""
    return [text for _, text in p.variants(source, 'slot') if 'object[1]' in text and '(u8) action;\n        if' not in text]


def test_the_first_assignment_goes_into_its_test():
    texts = first(SOURCE)
    assert len(texts) == 1
    assert '| (((u8) action) == 25))' in texts[0]
    assert 'object[id] = 1;' in texts[0] and texts[0].count('id = (u8) action;') == 1


def test_the_last_assignment_is_also_offered_inline():
    assert any('object[((u8) action)] = 1;' in text for _, text in p.variants(SOURCE, 'slot'))


def test_a_use_after_the_test_keeps_the_assignment():
    assert first(SOURCE.replace('object[1] = 2;', 'object[1] = id;')) == []


def test_a_value_that_reads_memory_or_calls_is_left_alone():
    for value in ('table[action]', 'f(action)'):
        source = SOURCE.replace('id = (u8) action;\n        if', f'id = {value};\n        if')
        assert all(f'id = {value};' in text for _, text in p.variants(source, 'slot'))


def test_a_loop_round_the_assignment_blocks_it():
    assert first(SOURCE.replace('if (object != 0) {', 'while (object[0] != 0) {')) == []
    fenced = SOURCE.replace('if (object != 0) {', 'do {').replace('        object[id] = 1;\n    }', '        object[id] = 1;\n    } while (0);')
    assert len(first(fenced)) == 1


def test_a_value_changed_inside_the_test_is_left_alone():
    assert first(SOURCE.replace('(id == 25)', '((action = 3) == id)')) == []


def test_it_declares_itself_to_the_registry():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'reassigned_local_inline')) == []
