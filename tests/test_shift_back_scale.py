"""shift_back_scale on made-up code."""
from decomprepair.registry import declared
from decomprepair.shift_back_scale import FAMILY, variants

SOURCE = '''typedef struct { u32 start; u32 length; } Entry;

void f(Entry *table, s32 i, s32 signedValue) {
    u32 bytes;
    s32 more;

    bytes = (table[i].length + 0xF) / 16 * 16;
    more = ((u32) (table[i].start + 7) >> 3) * 8;
    table[i].start = (bytes + 3) / 4 * 4;
    send(bytes, more);
}
'''


def test_every_site_then_each_site():
    out = [text for family, text in variants(SOURCE, 'f') if family == FAMILY]
    assert len(out) == 3
    assert 'bytes = ((table[i].length + 0xF) >> 4) << 4;' in out[0]
    assert 'more = ((u32) (table[i].start + 7) >> 3) << 3;' in out[0]
    # a destination in memory is left as written
    assert 'table[i].start = (bytes + 3) / 4 * 4;' in out[0]
    assert 'more = ((u32) (table[i].start + 7) >> 3) * 8;' in out[1]


def test_signed_or_mismatched_forms_are_left_alone():
    def body(line):
        return f'void f(s32 x, u32 y) {{\n    s32 r;\n    r = {line};\n    send(r);\n}}\n'
    for line in ('(x + 15) / 16 * 16', '(y + x) / 16 * 16', '(y + 15) / 16 * 8', '(y >> 4) * 8',
                 '(y + 15) / 12 * 12', 'x + (y >> 4) * 16'):
        assert variants(body(line), 'f') == [], line
    assert variants(body('(y + 15) / 16 * 16'), 'f')
    assert variants(body('((u32) (x + 15)) / 16 * 16'), 'f')


def test_it_is_registered():
    assert any(FAMILY in repair.families for repair in declared())
