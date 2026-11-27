"""Typed pointers stepped beside a loop counter, written as the table indexed by the counter."""
from decomprepair import registry
from decomprepair import stride_cursor_index as c

SOURCE = '''extern s32 gTable;
void f(void)
{
    s32 *base;
    s32 *used;
    s32 *text;
    s32 y;
    u32 i;

    y = 0x3C;
    i = 0;
    base = &gTable;
    used = base;
    text = base + 0x1;
    for (;;) {
        if (i < 8U) {
            if (*used != 0) {
                g(text, y);
            }
            y += 0xF;
            text += 17;
            used += 17;
            ++i;
            continue;
        }
        break;
    }
}
'''


def test_both_pointers_off_the_counter():
    (family, text), = c.variants(SOURCE, 'f')
    assert family == 'stride_cursor_index'
    assert 'if (*((s32 *) (&gTable) + i * 17) != 0)' in text
    assert 'g(((s32 *) (&gTable + 0x1) + i * 17), y);' in text
    assert 'base' not in text and 'used' not in text and 'text' not in text
    # the integer companion stays a counter of its own
    assert 'y = 0x3C;\n    i = 0;\n    for (;;)' in text and 'y += 0xF;\n            ++i;' in text


def test_do_loop_and_other_table_type():
    source = '''extern u8 gBytes[];
void f(void)
{
    Row *p;
    s32 i;

    i = 0;
    p = &gBytes + 2;
    do {
        g(p);
        p += 1;
        i++;
    } while (i < 4);
}
'''
    (_, text), = c.variants(source, 'f')
    assert 'g(((Row *) (&gBytes + 2) + i * 1));' in text


def test_left_alone_otherwise():
    assert c.variants(SOURCE.replace('        break;\n    }\n', '        break;\n    }\n    g(used, text);\n'), 'f') == []
    assert c.variants(SOURCE.replace('i = 0;', 'i = n;'), 'f') == []
    assert c.variants(SOURCE.replace('++i;', 'i += 2;'), 'f') == []
    # a pointer started from something that is not a symbol's address
    assert c.variants(SOURCE.replace('base = &gTable;', 'base = h();'), 'f') == []
    # a pointer read after its step
    read = SOURCE.replace('            ++i;\n', '            ++i;\n            g(used, 0);\n').replace('text += 17;', ';')
    assert c.variants(read, 'f') == []


def test_registered():
    assert registry.get('stride_cursor_index') is not None
