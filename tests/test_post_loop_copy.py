from decomprepair import registry
from decomprepair.post_loop_copy import FAMILY, REPAIR, variants

SOURCE = """s32 allocate(s32 arg0, Table *t) {
    s32 slot;
    u32 id;
    u32 seen;
    s32 count;
    s32 extra;
    slot = arg0 & 0xFF;
    extra = slot + 1;
    do {
        count = 0;
        seen = 0;
        id = gNextId;
        gNextId = (id + 1) & 0x7FFFFFFF;
        while (count < 8) {
            if (t->entry[count].id == id) {
                id = -1;
            }
            count += 1;
        }
    } while (id == -1);
    t->owner[slot] = id;
    return extra;
}
"""


def children(source=SOURCE):
    return [c for f, c in variants(source, 'allocate') if f == FAMILY]


def test_the_statement_after_the_loop_reads_a_copy_taken_before_it():
    got = children()
    assert got
    child = next(c for c in got if 't->owner[slot_copy] = id;' in c)
    assert child.index('slot_copy = slot;') < child.index('do {')
    assert 's32 slot_copy;' in child
    assert 't->owner[slot] = id;' not in child


def test_a_loop_with_a_call_is_left_alone():
    called = SOURCE.replace('            count += 1;', '            count += probe(count);')
    assert not any('slot_copy' in c for c in children(called))


def test_a_local_the_loop_reads_is_left_alone():
    read = SOURCE.replace('count += 1;', 'count += 1 + (slot & 0);')
    assert not any('t->owner[slot_copy]' in c for c in children(read))


def test_it_declares_itself():
    assert REPAIR['variants'] is variants
    assert FAMILY in {family for entry in registry.declared() for family in entry.families}
