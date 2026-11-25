"""A stray `v + 1` argument dropped with its store stepped in place (a 234-instruction N64 scene init, 10 -> 0)."""
from decomprepair.arity_drop_store_step import FAMILY, REPAIR, variants

SOURCE = """void notify(s32, s32, s32, ...);
void scene(Obj *arg0) {
    s32 id;

    id = arg0->state;
    if (id == 0) {
        id = gCounter;
        arg0->state = 1;
        arg0->slot = id + 470;
        gCounter = id + 1;
        notify(arg0->slot, 0xDAA, 0, id + 1);
        arg0->next = 14;
        return;
    }
    tick();
}
"""

CALLEES = """void notify(s32 a, s32 b, s32 c) {
    use(a, b, c);
}
"""


def children(source=SOURCE, callees=CALLEES):
    return [text for family, text in variants(source, 'scene', callees=callees) if family == FAMILY]


def test_drop_then_step_then_entry_inline():
    found = children()
    assert len(found) == 3
    assert 'notify(arg0->slot, 0xDAA, 0);' in found[0] and 'gCounter = id + 1;' in found[0]
    assert 'id++;\n        gCounter = id;\n        notify(arg0->slot, 0xDAA, 0);' in found[1]
    assert 'id = arg0->state;' in found[1]
    assert 'id = arg0->state;' not in found[2]
    assert '    if (arg0->state == 0) {\n        id = gCounter;' in found[2]
    assert 'id++;\n        gCounter = id;' in found[2]


def test_a_fixed_prototype_is_trimmed_with_the_call():
    source = SOURCE.replace('void notify(s32, s32, s32, ...);', 'void notify(s32, s32, s32, s32);')
    found = children(source)
    assert all('void notify(s32 a, s32 b, s32 c);' in text for text in found)


def test_value_read_after_the_store_keeps_the_sum():
    source = SOURCE.replace('arg0->next = 14;', 'arg0->next = id;')
    found = children(source)
    assert len(found) == 1 and 'gCounter = id + 1;' in found[0]


def test_entry_test_kept_when_the_value_is_read_after_the_block():
    source = SOURCE.replace('    tick();\n', '    tick(id);\n')
    found = children(source)
    assert len(found) == 1


def test_plain_names_and_calls_are_left_to_other_families():
    assert children(SOURCE.replace('0, id + 1);', '0, id);')) == []
    assert children(SOURCE.replace('0, id + 1);', '0, next(id));')) == []
    assert variants(SOURCE, 'scene') == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and 'callees' in REPAIR['needs']
