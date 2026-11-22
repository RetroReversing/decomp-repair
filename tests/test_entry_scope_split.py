"""A function's opening `do { } while (0)` ended between a pointer chain's two loads, and a sum's product staged before a
scope holding the add and a parameter copy.

Synthetic shape of the 851-instruction ray test's head (KMC GCC 2.7.2): the run already wrapped, a record's last
component summed from two pointer parameters beside the copy of the list parameter, the list copied to a spilled local
and its head's field read through two loads, then two global stores. From the saved best the pair went 70 -> 0 in the
isolated judge (the split alone 10, the stage alone 60)."""
from decomprepair import entry_scope_split as e

SOURCE = '''s32 cast(void **list, f32 *start, f32 *dir, f32 span)
{
    struct {
        f32 x;
        f32 z;
    } end;
    s32 (*cb)(f32 *);
    f32 dist;
    void **cursor;
    void **walk;
    void *head;

    do {
    dist = span;
    end.x = *start + (*dir * dist);
    walk = list;
    end.z = (M2C_FIELD(dir, f32 *, 8) * dist) + M2C_FIELD(start, f32 *, 8);
    cursor = walk;
    head = M2C_FIELD(M2C_FIELD(walk, void **, 0x20), void **, 0x58);
    gA = 0;
    gB = 0;
    } while (0);
    if (walk != 0) {
        cursor = *cursor;
    }
    return dist < span;
}
'''


def texts():
    found = e.variants(SOURCE, 'cast')
    assert all(family == e.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_chain_is_split_where_the_scope_ends():
    assert any('    link_walk = M2C_FIELD(walk, void **, 0x20);\n    cursor = walk;\n    } while (0);\n'
               '    head = M2C_FIELD(link_walk, void **, 0x58);\n    gA = 0;\n    gB = 0;\n' in t
               and '    void *link_walk;\n    do {' in t for t in texts())


def test_the_copy_of_the_base_also_stays_ahead_of_the_first_load_in_a_child():
    found = texts()
    assert any('    cursor = walk;\n    link_walk = M2C_FIELD(walk, void **, 0x20);\n    } while (0);' in t for t in found)


def test_the_product_is_staged_with_the_add_and_the_copy_in_a_scope_of_their_own():
    assert any('    staged_end_z = M2C_FIELD(dir, f32 *, 8) * dist;\n    do {\n'
               '        end.z = M2C_FIELD(start, f32 *, 8) + staged_end_z;\n        walk = list;\n    } while (0);\n' in t
               and '    f32 staged_end_z;\n' in t for t in texts())


def test_the_pair_is_offered_as_one_child():
    assert any('staged_end_z = ' in t and 'head = M2C_FIELD(link_walk, void **, 0x58);' in t for t in texts())


def test_nothing_without_an_opening_scope():
    unwrapped = SOURCE.replace('    do {\n', '', 1).replace('    } while (0);\n', '', 1)
    assert e.variants(unwrapped, 'cast') == []
    assert e.variants(SOURCE, 'missing') == []
