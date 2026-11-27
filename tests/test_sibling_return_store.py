from decomprepair import registry
from decomprepair.sibling_return_store import FAMILY, variants

LOOKUP = '''typedef struct Block { struct Block *next; s32 state; u32 addr; } Block;
extern Block *gUsed;
extern Block *gFree;

Block *lookup(u32 addr) {
    Block *n;
    Block *fresh;

    for (n = gUsed; n != 0; n = n->next) {
        if (n->addr == addr) {
            return n;
        }
    }
    fresh = gFree;
    fresh->addr = addr;
    fresh->state = 2;
    return fresh;
}
'''


def test_the_found_block_gets_the_fresh_blocks_state_store():
    wanted = LOOKUP.replace('            return n;', '            n->state = 2;\n            return n;')
    assert (FAMILY, wanted) in variants(LOOKUP, 'lookup')


def test_a_block_that_already_stores_the_field_is_left_alone():
    done = LOOKUP.replace('            return n;', '            n->state = 2;\n            return n;')
    assert variants(done, 'lookup') == []


def test_an_unbraced_return_is_braced():
    source = '''void *pick(Node *a, Node *b, int c) {
    if (c) return b;
    a->flags = -1;
    return a;
}
'''
    children = [child for _, child in variants(source, 'pick')]
    assert source.replace('if (c) return b;', 'if (c) { b->flags = -1; return b; }') in children


def test_other_types_and_computed_values_are_not_copied():
    source = '''Node *pick(Node *a, Leaf *b, int c) {
    Node *n;
    b->flags = 1;
    a->count = c;
    return n;
}
'''
    assert variants(source, 'pick') == []


def test_the_module_is_declared():
    assert registry.get('sibling_return_store').families == (FAMILY,)
