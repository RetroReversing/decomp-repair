"""Record field stores beside a scalar global's store, written as raw offset stores."""
from decomprepair import struct_store_raw_offsets as s

DRAFT = '''typedef struct { u8 id; u8 next; u8 pad[2]; f32 t; s16 len; s16 pos; } Cursor;
extern u8 G;
void f(Cursor *cur, u8 b) {
    cur->len = 3;
    g();
    b |= 1;
    G = b;
    cur->pos = -1;
    cur->t = 0.01f;
    g();
    cur->id = 2;
}
'''


def test_only_the_stores_beside_the_global_go_raw():
    out = [text for _, text in s.variants(DRAFT, 'f')]
    both = out[0]
    assert '*(s16 *)((u8 *)cur + 0xA) = -1;' in both and '*(f32 *)((u8 *)cur + 0x4) = 0.01f;' in both
    assert 'cur->len = 3;' in both and 'cur->id = 2;' in both
    assert len(out) == 3 and sum('*(s16 *)((u8 *)cur + 0xA)' in text for text in out) == 2


def test_nothing_without_a_known_layout_or_a_global():
    assert s.variants(DRAFT.replace('extern u8 G;', 'u8 G2;'), 'f') == []
    assert s.variants(DRAFT.replace('typedef struct', 'typedef struct X').replace('f32 t;', 'Vec t;'), 'f') == []
