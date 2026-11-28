"""m2c's typed pointer local over byte tables, read with byte offsets, declared `char *`."""
from decomprepair.byte_cursor_retype import FAMILY, variants
from decomprepair.m2cfix import refine_draft

SAVED = '''extern char D_80000010[];
extern char D_80000020[];

void f(void *arg0, s32 i) {
    s32 *var_a3;
    s32 v;

    if (arg0 != 0) {
        var_a3 = D_80000010;
        goto done;
    }
    var_a3 = D_80000020;
done:
    v = *(s32 *)((i * 8) + var_a3);
    G(v, *(s32 *)(((i * 8) | 4) + var_a3));
}
'''


def test_the_cursor_over_byte_tables_becomes_a_byte_pointer():
    [(family, child)] = variants(SAVED, 'f')
    assert family == FAMILY
    assert child == SAVED.replace('s32 *var_a3;', 'char *var_a3;')


def test_a_fresh_draft_gets_the_same_retype():
    asm = 'glabel func_80001000\njr $ra\nnop\nendlabel func_80001000\n'
    draft = SAVED.replace('void f(void *arg0, s32 i)', 'void func_80001000(void *arg0, s32 arg1)').replace('i * 8', 'arg1 * 8')
    assert 'char *var_a3;' in refine_draft(draft, 'func_80001000', asm)


def test_a_pointer_used_by_element_is_left_alone():
    for use in ('var_a3[i]', '*var_a3', 'var_a3->x', '*(s32 *)(i + var_a3)', '*(s32 *)((i * 2) + var_a3)'):
        assert variants(SAVED.replace('G(v,', f'G({use},'), 'f') == [], use


def test_a_value_that_is_not_a_byte_table_is_left_alone():
    assert variants(SAVED.replace('var_a3 = D_80000020;', 'var_a3 = arg0;'), 'f') == []
    assert variants(SAVED.replace('extern char D_80000020[];', 'extern s32 D_80000020[];'), 'f') == []
