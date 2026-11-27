"""A statement run written out twice becomes one `static inline` helper both places call."""
from decomprepair.repeated_run_helper import FAMILY, variants

SOURCE = """typedef struct { u8 table; u8 slot; } Link;
typedef struct { Link next[64]; } Chain;
s32 load(Chain *, u8);

s32 walk(s32 *limit, s32 count)
{
    s32 err;
    Chain chain;
    Link link;
    u8 cached;

    cached = 0xFF;
    link.table = 0;
    link.slot = 1;
    while (count >= 8) {
        if (link.table != cached) {
            cached = link.table;
            if ((err = load(&chain, cached)) != 0) {
                return err;
            }
        }
        link = chain.next[link.slot];
        if (link.slot >= *limit) {
            return 3;
        }
        count -= 8;
    }
    if (count > 0) {
        if (link.table != cached) {
            cached = link.table;
            if ((err = load(&chain, cached)) != 0) {
                return err;
            }
        }
        link = chain.next[link.slot];
        if (link.slot >= *limit) {
            return 3;
        }
        count = 0;
    }
    return count;
}
"""


def children(source):
    found = variants(source, 'walk')
    assert all(family == FAMILY for family, _ in found)
    return [child for _, child in found]


def test_run_written_twice_becomes_a_status_helper():
    made = children(SOURCE)
    child = next(c for c in made if 'walk_step(s32 *limit, u8 *cached, Chain *chain, Link *link)' in c)
    helper = child[child.index('static inline s32 walk_step'):child.index('s32 walk(')]
    assert 's32 err;' in helper and 'return 0;' in helper
    assert 'link->table != (*cached)' in helper
    assert '(*link) = chain->next[link->slot];' in helper
    assert 'load(chain, (*cached))' in helper
    body = child[child.index('s32 walk('):]
    # the variable the run returned takes the helper's result
    assert body.count('if ((err = walk_step(limit, &cached, &chain, &link)) != 0) {') == 2
    assert body.count('return err;') == 2
    # where the arguments take the locals' addresses is a choice: each order is a child
    assert any('walk_step(s32 *limit, Chain *chain, Link *link, u8 *cached)' in c for c in made)


def test_returned_values_must_be_known_nonzero():
    source = SOURCE.replace('            return 3;\n', '            err = 3;\n            return err;\n')
    # `err` returned after a plain assignment is not proof it is nonzero
    assert not any('return 0;' in c.split('s32 walk(')[0] and 'chain->' in c for c in children(source))
    # with only literal returns, a new variable takes the result
    source = SOURCE.replace("""            if ((err = load(&chain, cached)) != 0) {
                return err;
            }""", "            err = load(&chain, cached);")
    child = children(source)[0]
    assert 's32 walk_status;' in child and 'if ((walk_status = walk_step(' in child


def test_a_run_that_cannot_move_is_left_alone():
    assert not children(SOURCE.replace('return 3;', 'goto out;'))
    for child in children(SOURCE.replace('return 3;', 'return 0;')):
        assert 'return 0;\n  }' not in child.split('s32 walk(')[0]
