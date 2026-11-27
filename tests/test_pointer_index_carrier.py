"""A record pointer that first holds the widened index it is computed from."""
from decomprepair import pointer_index_carrier as r

# The shape of an N64 record initialiser (KMC GCC 2.7.2 -O1 -g), synthetic names.
SOURCE = '''extern char TABLE[];
s16 pick(s32, s32);

s32 f(s32 a, s16 id) {
    s16 slot;
    void *rec;

    slot = id;
    if ((id != -1) || (slot = pick(1, 3), (slot != id))) {
        rec = (slot * 0x24) + TABLE;
        *(s16 *)rec = a;
    }
    return slot;
}
'''


def test_the_pointer_carries_the_index_first():
    [(family, out)] = r.variants(SOURCE, 'f')
    assert family == 'pointer_index_carrier'
    assert '        rec = (void *)(s32)slot;\n        rec = (((s32)rec * 0x24) + TABLE);\n' in out
    assert '(slot * 0x24)' not in out


def test_base_first_and_element_address_forms():
    [(_, out)] = r.variants(SOURCE.replace('(slot * 0x24) + TABLE', 'TABLE + (slot * 0x24)'), 'f')
    assert 'rec = (TABLE + ((s32)rec * 0x24));' in out
    [(_, out)] = r.variants(SOURCE.replace('(slot * 0x24) + TABLE', '&TABLE[slot * 0x24]'), 'f')
    assert 'rec = (void *)(s32)slot;' in out and 'rec = (TABLE + ((s32)rec * 0x24));' in out


def test_a_typed_pointer_keeps_its_type():
    src = SOURCE.replace('void *rec;', 'Rec *rec;')
    [(_, out)] = r.variants(src, 'f')
    assert 'rec = (Rec *)(s32)slot;' in out and 'rec = (Rec *)(((s32)rec * 0x24) + TABLE);' in out


def test_left_alone_when_not_a_pointer_local_or_not_scaled_by_a_literal():
    assert r.variants(SOURCE.replace('void *rec;', 's32 rec;'), 'f') == []
    assert r.variants(SOURCE.replace('(slot * 0x24)', '(slot * a)'), 'f') == []
    assert r.variants(SOURCE.replace('(slot * 0x24) + TABLE', '(rec * 0x24) + TABLE'), 'f') == []
