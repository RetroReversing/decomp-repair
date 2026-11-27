"""Casted byte offsets written back as typed tables and records, and m2c's default-by-goto compare tree as a switch."""
from decomprepair import cast_offset_records, compare_tree_default_switch

SOURCE = '''extern char D_80300000[];
extern char D_80200000[];
extern char D_80200004[];

void f(s32 n) {
    s32 i;
    s32 t;
    s32 v0;
    s32 off;
    u16 v;

    i = 0;
    v0 = 0 * 4;
    do {
        t = (v0 + i) * 8;
        *(u16 *)(D_80300000 + 0x2108 + t) = n;
        if (n != 2) {
            if (n >= 3) {
                if (n != 3) { goto other; }
                v = *(u16 *)(D_80200000 + i * 2);
            } else {
other:
                v = *(u16 *)(D_80200004 + i * 2);
            }
        } else {
            v = *(u16 *)(D_80200000 + i * 2);
        }
        *((u16 *) ((D_80300000 + 0x210A) + t)) = v;
        i += 1;
        v0 = i * 4;
    } while (i < n);
}
'''


def test_records_and_tables_are_declared_and_the_offset_locals_go():
    text = cast_offset_records.variants(SOURCE, 'f')[0][1]
    assert 'extern u16 D_80200000[];' in text and 'D_80200004[i]' in text
    assert 'extern CastRow_D_80300000 D_80302108[];' in text
    assert 'D_80302108[i].m0 = n;' in text and 'D_80302108[i].m2 = v;' in text
    assert 'char pad4[0x24];' in text
    assert ' t = ' not in text and 'v0' not in text and 's32 t;' not in text


def test_the_pair_with_the_switch_is_one_child():
    out = [text for _, text in cast_offset_records.variants(SOURCE, 'f')]
    assert any('switch (n)' in text and 'D_80302108[i].m0' in text for text in out)


def test_a_symbol_with_another_use_is_left():
    other = SOURCE.replace('i = 0;\n    v0', 'i = 0;\n    g(D_80300000);\n    v0')
    assert 'extern char D_80300000[];' in cast_offset_records.variants(other, 'f')[0][1]


def test_tree_with_a_goto_default_reads_back_as_the_switch():
    text = compare_tree_default_switch.variants(SOURCE, 'f')[0][1]
    assert 'switch (n)' in text and 'case 2:' in text and 'case 3:' in text and 'default:' in text
    assert 'goto' not in text and 'other:' not in text


def test_the_arms_result_store_is_sunk_into_each_arm():
    text = compare_tree_default_switch.variants(SOURCE.replace('&', '&'), 'f')[0][1]
    assert '*((u16 *) ((D_80300000 + 0x210A) + t)) = *(u16 *)(D_80200004 + i * 2);' in text
    assert 'u16 v;' not in text


def test_an_empty_case_list_whose_default_does_the_work():
    source = '''void f(s32 i) {
    s32 v;

    v = D[i];
    if (v != 0x3FFF) {
        if ((v + 1) <= 0x4000) {
            if (v != 0x2FFF) {
                i = 0;
                goto body;
            }
        } else if (v != 0x4FFF) {
            i = 0;
body:
            g(i);
        }
    }
}
'''
    text = compare_tree_default_switch.variants(source, 'f')[0][1]
    assert 'case 0x2fff:\ncase' in text.replace('    ', '') and 'case 0x4fff:' in text and 'default:' in text
    assert 'goto' not in text


def test_a_range_that_leads_elsewhere_is_no_switch():
    source = '''void f(s32 v) {
    if (v != 2) {
        if (v >= 3) {
            if (v != 3) {
                a();
            } else {
                goto other;
            }
        } else {
other:
            b();
        }
    } else {
        c();
    }
}
'''
    assert compare_tree_default_switch.variants(source, 'f') == []
