from decomprepair import stepped_constant_row_giv as rg

# The shape of a nine-row N64 menu loop (SN64 GCC 2.8.1): a constant-stepped y in both arms of an if/else.
SOURCE = """\
void draw(void *arg0)
{
    s32 y;
    s32 i;
    s32 n;
    n = D_start + 9;
    i = D_start;
    if (i < n) {
        y = 0x37;
        do {
            text(0x28, y);
            if (flags[i] == 0) {
                text(0x41, y);
                do { y += 0xE; } while (0);
            } else {
                text(0x42, y);
                do { y += 0xE; } while (0);
            }
            i += 1;
        } while (i < n);
    }
}
"""


def test_the_stepped_local_becomes_a_giv_of_a_row_counter_stepped_before_the_loop_counter():
    family, text = rg.variants(SOURCE, 'draw')[0]
    assert family == 'stepped_constant_row_giv'
    assert 'y += 0xE' not in text
    assert 's32 row;' in text
    assert 'row = 0;' in text and 'y = 0x37;' not in text
    body = text[text.index('do {'):]
    assert body.index('y = row * 0xE + 0x37;') < body.index('text(0x28, y);')
    # row++ must come before the counter's step: bivs are reduced newest-first, so y's li is emitted last
    assert body.index('row++;') < body.index('i += 1;')


def test_row_step_after_the_counter_is_offered_second():
    texts = [t for _, t in rg.variants(SOURCE, 'draw')]
    assert len(texts) >= 2
    body = texts[1][texts[1].index('do {'):]
    assert body.index('i += 1;') < body.index('row++;')


def test_a_single_step_at_the_body_level_and_a_for_loop():
    source = """\
void f(void)
{
    s32 x;
    s32 i;
    x = 16;
    for (i = 0; i < 4; i++) {
        put(i, x);
        x += 8;
    }
}
"""
    family, text = rg.variants(source, 'f')[0]
    assert 'x = row * 8 + 16;' in text and 'x += 8' not in text
    assert text.index('put(i, x);') < text.index('row++;')


def test_declines_when_a_pass_may_skip_the_step_or_the_value_is_read_after_the_loop():
    one_arm = SOURCE.replace("text(0x42, y);\n                do { y += 0xE; } while (0);", "text(0x42, y);")
    assert rg.variants(one_arm, 'draw') == []
    read_after = SOURCE.replace("        } while (i < n);\n    }\n", "        } while (i < n);\n    }\n    text(0, y);\n")
    assert rg.variants(read_after, 'draw') == []
    escape = SOURCE.replace("text(0x41, y);", "text(0x41, y);\n                if (y > 99) break;")
    assert rg.variants(escape, 'draw') == []
    address = SOURCE.replace("text(0x28, y);", "text(0x28, y);\n            take(&y);")
    assert rg.variants(address, 'draw') == []


def test_a_fenced_initialiser_goes_with_its_fence():
    fenced = SOURCE.replace("        y = 0x37;\n", "        do { y = 0x37; } while (0);\n")
    family, text = rg.variants(fenced, 'draw')[0]
    assert 'row = 0;' in text and 'do { row = 0; } while (0);' not in text and 'y = 0x37' not in text
