"""A stream cursor kept in a field, read through saved old values, written back as `*field++` at every site."""
from decomprepair import scaffold_strip
from decomprepair.cursor_field_postincrement import COMBINED, FAMILY, variants

CURSOR = '(*(u8 **)((s8 *)obj + 0x20))'
SOURCE = f'''static __inline__ u8 same(u8 a) {{ return a; }}

void read_stream(void *obj) {{
    union {{ u8 * pointer; unsigned int value; }} shared;
    s32 high;
    u8 *first;
    u8 *second;
    u8 *third;
    u8 byte;

    shared.pointer = {CURSOR};
    first = shared.pointer;
    {CURSOR} = (u8 *) (first + 1);
    byte = same(*first);
    shared.value = (u8)( byte & 0xFF);
    if (((u8)shared.value) >= 0x80U) {{
        second = {CURSOR};
        {CURSOR} = (u8 *) (second + 1);
        (*(s32 *)((s8 *)obj + 0x10)) = byte;
        byte = *second;
        third = {CURSOR};
        high = byte << 8;
        (*(u16 *)((s8 *)obj + 0x24)) = high;
        {CURSOR} = (u8 *) (third + 1);
        (*(u16 *)((s8 *)obj + 0x24)) = (u16) (*third + (high + 2));
    }} else {{
        (*(s32 *)((s8 *)obj + 0x10)) = (u8)shared.value;
    }}
}}
'''


def test_every_site_is_written_as_a_post_increment_and_the_scaffolding_stripped():
    children = variants(SOURCE, 'read_stream')
    full = [text for family, text in children if family == COMBINED and text.count(f'*{CURSOR}++') == 3]
    assert full
    body = full[0][full[0].index('void read_stream'):]
    for gone in ('first', 'second', 'third', 'shared', 'same('):
        assert gone not in body
    assert f'(u16) (*{CURSOR}++ + (high + 2))' in body
    assert 'if (((u8)byte) >= 0x80U)' in body


def test_a_single_old_value_is_rewritten_and_its_declaration_dropped():
    source = '''void f(Voice *voice) {
    u8 *old;
    u8 byte;
    old = voice->cursor;
    voice->cursor = old + 1;
    voice->rate = 1;
    byte = *old;
    voice->kind = byte;
}
'''
    (family, text), *_ = variants(source, 'f')
    assert family == FAMILY
    assert 'byte = *voice->cursor++;' in text
    assert 'old' not in text
    assert text.index('voice->rate = 1;') < text.index('byte = *voice->cursor++;')


def test_a_void_pointer_field_is_read_with_the_old_values_type():
    source = '''void f(void *arg0) {
    u8 *old;
    u8 byte;
    old = M2C_FIELD(arg0, void **, 0x34);
    M2C_FIELD(arg0, void **, 0x34) = (void *) (old + 1);
    byte = *old;
    M2C_FIELD(arg0, u8 *, 0x38) = byte;
}
'''
    (_, text), *_ = variants(source, 'f')
    assert 'byte = *M2C_FIELD(arg0, u8 **, 0x34)++;' in text


def test_the_step_does_not_move_past_what_could_see_it():
    shape = '''void f(Voice *voice, u8 **other) {
    u8 *old;
    u8 byte;
    old = voice->cursor;
    voice->cursor = old + 1;
    %s
    byte = *old;
    voice->kind = byte;
}
'''
    for between in ('advance(voice);', '*other = 0;', 'if (voice->kind) { voice->rate = 1; }'):
        assert variants(shape % between, 'f') == []
    # the old value read again afterwards keeps its own local
    assert variants(shape % 'voice->rate = 1;', 'f')
    again = (shape % 'voice->rate = 1;').replace('voice->kind = byte;', 'voice->kind = byte + *old;')
    assert variants(again, 'f') == []


def test_scaffold_strip_unwraps_a_deeply_nested_call_of_a_gnu_inline_identity():
    source = '''static __inline__ u8 same(u8 a) { return a; }

void f(void *obj) {
    u8 byte;
    byte = same(*(*(u8 **)((s8 *)obj + 0x34))++);
    *(u8 *)obj = byte;
}
'''
    text = scaffold_strip.strip(source, 'f')
    assert 'byte = (*(*(u8 **)((s8 *)obj + 0x34))++);' in text


def test_scaffold_strip_reads_a_word_copy_of_a_byte_as_the_byte():
    source = '''void f(u8 *p) {
    unsigned int wide;
    u8 byte;
    byte = *p;
    wide = (u8)( byte & 0xFF);
    if ((u8)wide >= 0x80U) {
        p[1] = byte;
    } else {
        p[2] = (u8)wide;
    }
}
'''
    text = scaffold_strip.strip(source, 'f')
    assert 'wide' not in text
    assert '(u8)byte >= 0x80U' in text and 'p[2] = (u8)byte;' in text
    # a copy of the low bits of something wider is not the value itself
    wider = source.replace('u8 byte;', 'u32 byte;')
    assert 'wide' in (scaffold_strip.strip(wider, 'f') or wider)
