"""A pointer local set to a global's address, declared far above the one nested block that uses it."""
from decomprepair.address_local_scope_sink import FAMILY, USES_FAMILY, variants

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


# A record pointer declared at the top of an outer `if`, used only inside the inner one.
CHECKS = '''extern Rec record;
extern short state[];
void f(void) {
    if (mode == 2) {
        Rec *rec = &record;
        if (state[0] == 0) {
            call(rec->a);
            if (rec->b < 4) {
                flags |= rec->c;
            }
        }
    }
}
'''


def test_a_pointer_used_many_times_moves_into_the_block_that_holds_every_use():
    out = [src for fam, src in variants(CHECKS, 'f') if fam == USES_FAMILY]
    assert len(out) == 1
    assert 'if (state[0] == 0) { Rec *rec = &record; call(rec->a);' in _squash(out[0])


def test_a_pointer_set_again_stays_where_it_is():
    for change in ('rec++;', 'rec = other;', 'rec += 1;', 'take(&rec);'):
        assert variants(CHECKS.replace('flags |= rec->c;', 'flags |= rec->c; ' + change), 'f') == []


def test_a_store_through_the_pointer_is_not_a_change_of_it():
    assert variants(CHECKS.replace('flags |= rec->c;', 'rec->c = 0; *rec = other; rec[1] = other; take(&rec->a);'), 'f')


def test_a_pointer_used_in_its_own_block_stays_where_it_is():
    flat = SAVED.replace('do {', '*entries = 0;\n        do {', 1).replace('s32 *slot = (s32 *) ((((s32) (index << 16)) >> 14) + ((s8 *) entries));', 's32 *slot = 0;')
    assert variants(flat, 'f') == []


def test_a_pointer_not_set_to_an_address_stays_where_it_is():
    assert variants(SAVED.replace('(s32 *) (&table)', 'buf'), 'f') == []
