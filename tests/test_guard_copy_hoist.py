"""A pure copy that opens an `if` arm, moved above the `if`."""
from decomprepair import guard_copy_hoist as p
from decomprepair import registry

SOURCE = '''typedef unsigned char u8;
typedef int s32;

s32 slot(u8 *object, u8 action, s32 value)
{
    s32 id; short j;
    id = (u8) action;
    if (((unsigned) id) < 31) {
        j = (u8) action;
        object[j] = value;
        return 1;
    }
    return 0;
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'slot')]


def test_the_copy_moves_above_its_guard():
    [text] = texts(SOURCE)
    assert 'j = (u8) action; if (((unsigned) id) < 31) {\n        object[j] = value;' in text
    assert text.count('j = (u8) action;') == 1


def test_the_judged_shape_is_reached():
    """The slot setter's step (15 -> 0): the late copy above `if (id < 31)`."""
    source = SOURCE.replace('''if (((unsigned) id) < 31) {
        j = (u8) action;
        object[j] = value;
        return 1;
    }''', 'if (((unsigned) id) < 31) { j = (u8) action; *((short *) (object + 0x138)) = j | (((u8) value) << 8); return 1; }')
    assert texts(source) == [source.replace('if (((unsigned) id) < 31) { j = (u8) action; ',
                                            'j = (u8) action; if (((unsigned) id) < 31) { ')]


def test_a_guard_that_reads_the_local_is_left_alone():
    assert texts(SOURCE.replace('((unsigned) id) < 31', 'j < 31')) == []


def test_a_read_after_the_arm_blocks_it():
    assert texts(SOURCE.replace('return 0;\n}', 'return j;\n}')) == []


def test_an_else_or_a_memory_value_blocks_it():
    assert texts(SOURCE.replace('return 1;\n    }', 'return 1;\n    } else { value = 2; }')) == []
    assert texts(SOURCE.replace('j = (u8) action;', 'j = object[0];')) == []


def test_it_declares_itself_to_the_registry():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'guard_copy_hoist')) == []
