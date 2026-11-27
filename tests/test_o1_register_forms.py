"""Spellings GCC 2.7.2 at -O1 keeps apart: an empty fence that ends cse's block, a subterm kept in an idle local."""
from decomprepair import o1_register_forms as forms
from decomprepair import registry

SOURCE = '''void f(s32 i, s32 y) {
    s32 n;

    if (i == 2) {
        n = i + 1;
        draw(n);
    } else {
        if (table[i] != 0) {
            frame(1, 2);
            picture(table[i]);
        }
        row(i * 14 + 0x3A + y);
    }
}
'''


def test_a_fence_goes_before_each_call_up_to_the_one_that_reads_the_tested_table():
    out = [child for family, child in forms.variants(SOURCE, 'f') if family == 'empty_cse_fence']
    assert len(out) == 2
    assert 'do { } while (0); frame(1, 2);' in out[0]
    assert 'do { } while (0); picture(table[i]);' in out[1]


def test_a_product_heading_an_argument_goes_into_a_local_that_is_idle_there():
    out = [child for family, child in forms.variants(SOURCE, 'f') if family == 'subterm_into_idle_local']
    assert len(out) == 1
    assert 'row((n = i * 14) + 0x3A + y);' in out[0]


def test_a_local_still_to_be_read_is_not_borrowed():
    live = SOURCE.replace('        draw(n);\n', '        row(i * 14 + y);\n        draw(n);\n')
    out = [child for family, child in forms.variants(live, 'f') if family == 'subterm_into_idle_local']
    assert all('        row((n = i * 14) + y);' not in child for child in out)
    outside = SOURCE.replace('    if (i == 2) {', '    n = y;\n    if (i == 2) {').replace('        n = i + 1;\n', '').replace(
        'y);\n    }\n}', 'y);\n    }\n    draw(n);\n}')
    spans = [child for family, child in forms.variants(outside, 'f') if family == 'subterm_into_idle_local']
    assert not spans


def test_declared():
    assert any(repair.module == 'o1_register_forms' for repair in registry.declared())


def test_a_local_assigned_after_a_case_label_can_be_borrowed():
    source = SOURCE.replace('    if (i == 2) {\n        n = i + 1;\n        draw(n);\n    } else {',
                            '    switch (y) {\n    case 2:\n        n = i + 1;\n        draw(n);\n        break;\n    }\n    {')
    out = [child for family, child in forms.variants(source, 'f') if family == 'subterm_into_idle_local']
    assert len(out) == 1


STEP = '''void f(s32 i) {
    Rect *r;
    s32 n;

    n = i;
    r = (Rect *) &config;
    height = r->y1 - r->y0;
    object[i].alpha += 1.0f;
    object[i].fade -= 1.0f;
    object[i].width += 1.5f;
    r = find(i);
}
'''


def test_a_fence_follows_a_pointer_set_from_an_address_only():
    out = [child for family, child in forms.variants(STEP, 'f') if family == 'address_then_fence']
    assert len(out) == 1
    assert 'r = (Rect *) &config; do { } while (0);' in out[0]


def test_a_float_step_of_one_becomes_a_postfix_step():
    out = [child for family, child in forms.variants(STEP, 'f') if family == 'float_step_postfix']
    assert len(out) == 2
    assert 'object[i].alpha++;' in out[0]
    assert 'object[i].fade--;' in out[1]
