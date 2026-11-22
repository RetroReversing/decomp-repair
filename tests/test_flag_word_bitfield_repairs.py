"""A masked flag-word update with a byte stored over it, as bit-fields (a synthetic object, not a game's code)."""
from decomprepair import flag_word_bitfield_repairs as f

SOURCE = '''typedef struct {
    u8 pad[0x1e];
    s16 scale;
    u16 x, y;
    u32 flags;
} Obj;
extern Obj *gObj;
extern u16 gX, gY;
extern volatile u16 gC;
void place(void) {
    volatile Obj *obj;
    u16 x, y; u8 color;
    u32 flags;
    obj = gObj;
    x = gX;
    y = gY;
    flags = obj->flags;
    obj->x = x;
    color = gC;
    obj->scale = 0x1000;
    obj->y = y;
    obj->flags = (flags & ~0xfc) | 0x1c;
    *(volatile u8 *)&obj->flags = color;
}
'''


def test_the_bit_field_spelling_and_its_chain():
    out = dict.fromkeys(text for _, text in f.variants(SOURCE, 'place'))
    assert all(family == f.FAMILY for family, _ in f.variants(SOURCE, 'place'))
    plain = [t for t in out if 'volatile Obj *obj' in t and 'obj->scale = 0x1000;\n    obj->x' not in t]
    assert plain and 'u32 flags_byte:8; u32 flags_mid:16; u32 flags_set:6; u32 flags_low:2;' in plain[0]
    assert 'obj->flags_set = 7;' in plain[0] and 'obj->flags_byte = color;' in plain[0]
    assert 'flags = obj->flags' not in plain[0] and 'u32 flags;\n' not in plain[0]
    chain = [t for t in out if 'volatile Obj' not in t and t.index('obj->scale = 0x1000;') < t.index('obj->x = x;')]
    assert chain


def test_without_the_byte_store_the_word_is_one_wider_middle():
    src = SOURCE.replace('    *(volatile u8 *)&obj->flags = color;\n', '')
    (family, text), *_ = f.variants(src, 'place')
    assert 'u32 flags_mid:24; u32 flags_set:6; u32 flags_low:2;' in text and 'flags_byte' not in text


def test_left_alone_otherwise():
    assert f.variants(SOURCE.replace('& ~0xfc', '& ~0xf5'), 'place') == []   # not one run of bits
    assert f.variants(SOURCE.replace('| 0x1c', '| 0x101'), 'place') == []    # a bit outside the mask
    assert f.variants(SOURCE.replace('    u32 flags;\n};', ''), 'other') == []
    assert f.variants(SOURCE.replace('    obj->flags = (flags & ~0xfc) | 0x1c;\n', '    obj->flags = flags + 1;\n'), 'place') == []
