"""copy_sink_to_clobber: a copy moved down to just before the statement that overwrites its source.

Synthetic shape of a 398-instruction SN64 GCC 2.8.1 glyph printer (330 -> 0: `ch = c;` made where c is reused)."""
from decomprepair import copy_sink_to_clobber as s

SOURCE = '''void glyph(s32 c, s32 first) {
    u8 ch;
    s32 special;

    ch = c;
    special = 0;
    if (c == '{') {
        draw(c);
        special = 1;
    }
    if (special) {
        return;
    }
    c = gTable[c];
    put(c, ch);
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'glyph') if family == s.FAMILY]


def test_the_copy_moves_to_just_before_the_overwrite():
    (text,) = _texts()
    assert '    special = 0;' in text and text.index('special = 0;') < text.index('ch = c;')
    assert '    }\n    ch = c;\n    c = gTable[c];\n' in text
    assert text.count('ch = c;') == 1


def test_a_read_of_the_copy_or_a_write_of_the_source_between_declines():
    read = SOURCE.replace('        draw(c);', '        draw(ch);')
    assert _texts(read) == []
    written = SOURCE.replace('        draw(c);', '        c++;')
    assert _texts(written) == []


def test_no_overwrite_or_a_goto_declines():
    assert _texts(SOURCE.replace('    c = gTable[c];\n    put(c, ch);', '    put(c, ch);')) == []
    assert _texts(SOURCE.replace('    special = 0;', '    special = 0;\nagain:')) == []
