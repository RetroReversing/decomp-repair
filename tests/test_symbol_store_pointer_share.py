"""`T[idx] = v;` in a loop through a pointer the function also reads T with (an N64 level loader, 15 rows -> 0)."""
from decomprepair.symbol_store_pointer_share import FAMILY, variants

HEADER = 'extern s32 D_tab[];\nextern s32 *D_paths[];\n'
SOURCE = """s32 load(s32 count, s32 *p)
{
    s32 i;
    s32 idx;
    s32 cnt;

    for (i = 0; i < count; i++) {
        if (p[0] == 3) {
            idx = p[1];
            cnt = p[2];
            D_tab[idx] = cnt;
            p += cnt * 3 + 3;
        } else {
            p += 6;
        }
    }
    if (check() != 0) {
        use(0, D_tab[0], D_paths[0]);
    }
    return count;
}
"""


def test_the_store_and_the_other_read_go_through_one_pointer_local():
    found = variants(SOURCE, 'load', HEADER)
    assert [family for family, _ in found] == [FAMILY]
    text = found[0][1]
    assert '    s32 *D_tab_p;\n' in text
    assert '            D_tab_p = D_tab;\n            D_tab_p[idx] = cnt;\n' in text
    assert '        D_tab_p = D_tab;\n        use(0, D_tab_p[0], D_paths[0]);\n' in text
    assert text.index('s32 *D_tab_p;') < text.index('for (')


def test_the_table_may_be_declared_in_the_source():
    assert len(variants(HEADER + SOURCE, 'load')) == 1


def test_a_store_outside_a_loop_or_a_table_used_once_is_left_alone():
    assert variants(SOURCE.replace('use(0, D_tab[0], D_paths[0]);', 'use(0, 0, D_paths[0]);'), 'load', HEADER) == []
    outside = SOURCE.replace('            D_tab[idx] = cnt;\n', '').replace('    return count;', '    D_tab[1] = 2;\n    return count;')
    assert variants(outside, 'load', HEADER) == []
