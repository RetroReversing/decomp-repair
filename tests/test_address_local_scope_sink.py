"""A pointer local set to a global's address, declared far above the one nested block that uses it."""
from decomprepair.address_local_scope_sink import FAMILY, variants

# A table append (KMC GCC 2.7.2): `entries` is declared with the loop's locals and used once, at the end of an arm.
SAVED = '''extern void *table;
extern u16 used;
void f(s32 *buf, s32 n) {
    s8 *cursor;
    cursor = buf;
    if (n != 0) {
        s32 *entries = (s32 *) (&table);
        do {
            cursor += 1;
            {
                u16 index = used;
                u16 next = index + 1;
                s32 *slot = (s32 *) ((((s32) (index << 16)) >> 14) + ((s8 *) entries));
                used = next;
                *slot = n;
            }
        } while (*cursor != 0);
    }
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_declaration_moves_into_the_block_that_uses_it():
    out = [src for fam, src in variants(SAVED, 'f') if fam == FAMILY]
    assert len(out) == 1
    squashed = _squash(out[0])
    assert 'if (n != 0) { do {' in squashed
    assert 'u16 next = index + 1; s32 *entries = (s32 *) (&table); s32 *slot =' in squashed


def test_a_pointer_used_twice_stays_where_it_is():
    assert variants(SAVED.replace('used = next;', 'used = next; *entries = 0;'), 'f') == []


def test_a_pointer_used_in_its_own_block_stays_where_it_is():
    flat = SAVED.replace('do {', '*entries = 0;\n        do {', 1).replace('s32 *slot = (s32 *) ((((s32) (index << 16)) >> 14) + ((s8 *) entries));', 's32 *slot = 0;')
    assert variants(flat, 'f') == []


def test_a_pointer_not_set_to_an_address_stays_where_it_is():
    assert variants(SAVED.replace('(s32 *) (&table)', 'buf'), 'f') == []
