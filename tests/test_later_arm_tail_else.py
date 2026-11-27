"""A goto from one if into the tail of a later one, written as two arms that each end with that tail."""
from decomprepair import registry
from decomprepair.later_arm_tail_else import FAMILY, variants

DRAFT = '''s32 pick(void *arg0, s32 *arg1) {
    s32 kind;
    s32 ret;
    s32 dead;
    s32 size;

    prepare();
    do { kind = M2C_FIELD(arg0, s32 *, 0);
    if (kind == 0) {
        size = 3;
        ret = size + 8;
        goto block_4;
    } } while (0);
    dead = 0x18;
    if (kind == 1) {
        size = 5;
        ret = size + 9;
block_4:
        *arg1 = size;
        dead = ret;
    }
    return ret;
}
'''

TAIL = '*arg1 = size;\n        dead = ret;'


def children(source=DRAFT):
    return [text for family, text in variants(source, 'pick') if family == FAMILY]


def test_each_arm_ends_with_the_tail():
    first, preset = children()
    assert 'goto' not in first and 'block_4' not in first and 'while (0)' not in first
    assert first.count(TAIL) == 2
    assert '} else' in first and 'if (kind == 1)' in first
    assert 'dead = 0x18' not in first


def test_second_child_gives_the_returned_local_the_dropped_default():
    first, preset = children()
    assert '    ret = 0x18;\n    prepare();' in preset
    assert preset.count(TAIL) == 2


def test_a_read_local_keeps_its_assignment_and_blocks_the_child():
    assert not children(DRAFT.replace('return ret;', 'return ret + dead;'))


def test_a_second_user_of_the_label_blocks_it():
    assert not children(DRAFT.replace('prepare();', 'prepare();\n    if (arg1) goto block_4;'))


def test_an_else_blocks_it():
    assert not children(DRAFT.replace('    return ret;\n', '    else { ret = 1; }\n    return ret;\n'))


def test_registry_declares_it():
    assert any(repair.module == 'later_arm_tail_else' for repair in registry.declared())
