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


# A three-row options menu (SN64 GCC 2.8.1, 525 -> 205 with no do-while fence): the body is a switch on the counter whose
# arms end in `break`; those leave the switch, not the loop, so every pass still steps y once.
SWITCH = """\
void menu(s32 sel)
{
    s32 i;
    s32 y;
    i = 0;
    y = 0x50;
    for (; i < 3; i++) {
        put(0xA0, y);
        switch (i) {
        case 0:
            if (sel == i) {
                bar(0);
            }
            for (sel = 0; sel < 5; sel++) {
                put(sel, y);
            }
            break;
        default:
            bar(2);
            break;
        }
        y += 10;
    }
}
"""


def test_a_switch_whose_breaks_leave_only_the_switch():
    texts = [t for f, t in rg.variants(SWITCH, 'menu') if f == rg.FAMILY]
    assert texts
    text = texts[0]
    assert 'y = row * 10 + 0x50;' in text and 'y += 10;' not in text and 'row = 0;' in text
    body = text[text.index('for (; i < 3; i++) {'):]
    assert body.index('y = row * 10 + 0x50;') < body.index('put(0xA0, y);')
    assert body.index('row++;') > body.index('switch (i)')


def test_a_switch_arm_that_leaves_the_loop_still_declines():
    for escape in ('return;', 'continue;', 'goto out;'):
        source = SWITCH.replace('            bar(2);\n', f'            bar(2);\n            {escape}\n')
        assert not [t for f, t in rg.variants(source, 'menu') if 'y = row' in t]
    # a break outside any switch or inner loop leaves the loop itself
    source = SWITCH.replace('        y += 10;\n', '        if (sel) {\n            break;\n        }\n        y += 10;\n')
    assert not [t for f, t in rg.variants(source, 'menu') if 'y = row' in t]


def test_the_loops_own_counter_when_it_starts_at_zero():
    source = SWITCH.replace('    y = 0x50;\n', '    y = 0x50;\n    yoff = 0;\n').replace(
        '        y += 10;\n', '        y += 10;\n        yoff += 10;\n').replace(
        '    s32 y;\n', '    s32 y;\n    s32 yoff;\n').replace('put(sel, y);', 'put(sel, y + yoff);')
    texts = [t for f, t in rg.variants(source, 'menu') if f == rg.FAMILY]
    own = [t for t in texts if 'y = i * 10 + 0x50;' in t and 'row' not in t]
    assert own and 'y = 0x50;' not in own[0] and 'y += 10;' not in own[0]
    yoff = [t for t in texts if 'yoff = i * 10;' in t]
    assert yoff and all('yoff += 10;' not in t and 'yoff = 0;' not in t for t in yoff)
    # after the body's leading giv of the counter as well as first
    staged = SWITCH.replace('    for (; i < 3; i++) {\n', '    for (; i < 3; i++) {\n        z = i * 4 + 1;\n').replace(
        '    s32 y;\n', '    s32 y;\n    s32 z;\n').replace('put(0xA0, y);', 'put(z, y);')
    tops = [t for f, t in rg.variants(staged, 'menu') if 'y = i * 10 + 0x50;' in t]
    assert any(t.index('y = i * 10') < t.index('z = i * 4') for t in tops)
    assert any(t.index('z = i * 4') < t.index('y = i * 10') for t in tops)


def test_no_counter_form_when_the_counter_does_not_start_at_zero():
    for start in ('    i = 1;\n', '    if (sel) {\n        i = 0;\n    }\n'):
        source = SWITCH.replace('    i = 0;\n', start)
        assert not [t for f, t in rg.variants(source, 'menu') if 'y = i * 10' in t]
    written = SWITCH.replace('        put(0xA0, y);\n', '        put(0xA0, y);\n        i += 0;\n')
    assert not [t for f, t in rg.variants(written, 'menu') if 'y = i * 10' in t]


# The same menu's bar loops (100 -> 25 -> 0 with the arms' temporary inlined): `x` and `k` started and stepped in the
# `for` header became givs of the counter, `x` first.
BARS = """\
void bars(s32 *lv, s32 yoff)
{
    s32 j;
    s32 k;
    s32 x;
    s32 yy;
    if (lv[0]) {
        for (j = 0, yy = yoff, k = 0, x = 0xA0; j < 5; k += 20, j++, x += 10) {
            put(x, yy + 0x50);
            fill(k >= lv[0]);
        }
    } else {
        for (j = 0, yy = yoff, k = 0, x = 0xA0; j < 5; k += 20, j++, x += 10) {
            put(x, yy + 0x50);
            fill(k >= lv[1]);
        }
    }
}
"""


def test_header_stepped_locals_become_givs_of_the_counter():
    texts = [t for f, t in rg.variants(BARS, 'bars') if f == rg.FAMILY]
    both = [t for t in texts if t.count('for (j = 0, yy = yoff; j < 5; j++) {') == 2]
    assert both
    want = 'for (j = 0, yy = yoff; j < 5; j++) {\n            x = j * 10 + 0xA0;\n            k = j * 20;\n'
    assert any(t.count(want) == 2 for t in both)
    assert any('k = j * 20;\n            x = j * 10 + 0xA0;' in t for t in both)
    assert any(t.count('for (j = 0, yy = yoff; j < 5; j++) {') == 1 for t in texts)


def test_header_givs_decline_a_local_read_outside_the_loops():
    read = BARS.replace('    if (lv[0]) {', '    x = 3;\n    put(x, 0);\n    if (lv[0]) {')
    assert not [t for f, t in rg.variants(read, 'bars') if 'x = j * 10' in t]
    nonzero = BARS.replace('for (j = 0, yy', 'for (j = 1, yy')
    assert not [t for f, t in rg.variants(nonzero, 'bars') if 'j * 10' in t]
    written = BARS.replace('            put(x, yy + 0x50);\n', '            put(x, yy + 0x50);\n            k++;\n', 1)
    first = [t for f, t in rg.variants(written, 'bars') if 'k = j * 20' in t]
    assert first and all(t.index('k = j * 20') > t.index('k++;') for t in first)  # only the loop that never writes k
