from decomprepair import registry
from decomprepair.float_temp_chain_fold import FAMILY, variants

SOURCE = """
void lerp(char *out, const char *a, const char *b, f32 t, int n) {
    f32 x0;
    f32 x1;
    f32 y0;
    f32 y1;
    char *po;
    char *pa;
    char *pb;
    int i;

    i = 0;
    po = out;
    pa = a;
    pb = b;
loop: {
        x0 = (*(const f32 *)((char *)(pb) + 8));
        y0 = (*(const f32 *)((char *)(pa) + 8));
        x0 -= y0;
        y1 = (*(const f32 *)((char *)(pa) + 0xC));
        x1 = ((*(const f32 *)((char *)(pb) + 0xC))) - y1;
        x0 *= t;
        x1 *= t;
        x0 += y0;
        pb += 0xC;
        pa += 0xC;
        i += 2;
        (*(f32 *)((char *)(po) + 8)) = x0;
        (*(f32 *)((char *)(po) + 0xC)) = (f32) (x1 + y1);
        po += 0xC;
    }
    if (i < n) goto loop;
}
"""


def test_folds_the_temporaries_into_one_expression_per_store():
    [(family, revised)] = variants(SOURCE, 'lerp')
    assert family == FAMILY
    assert ('(*(f32 *)((char *)(po) + 8)) = (((((*(const f32 *)((char *)(pb) + 8))) - (((*(const f32 *)((char *)(pa) + 8)))))'
            ' * (t)) + (((*(const f32 *)((char *)(pa) + 8)))));') in revised
    assert 'x0' not in revised.split('loop: {')[1] and 'y1' not in revised.split('loop: {')[1]
    # the stores come first, the pointer steps after them, so every read still sees the pointers it saw
    assert revised.index('(po) + 8)) =') < revised.index('pb += 0xC;') < revised.index('po += 0xC;')
    assert variants(revised, 'lerp') == []


def test_declines_when_a_temporary_is_used_later():
    assert variants(SOURCE.replace('po += 0xC;\n', 'po += 0xC;\n        t = x0;\n'), 'lerp') == []


def test_declines_when_a_pointer_step_comes_before_a_read():
    moved = SOURCE.replace('        pb += 0xC;\n', '').replace('        x1 = ', '        pb += 0xC;\n        x1 = ')
    assert variants(moved, 'lerp') == []


def test_declines_when_the_store_pointer_is_read_through():
    assert variants(SOURCE.replace('(po) + 8)) = x0', '(pa) + 8)) = x0'), 'lerp') == []


def test_declines_a_run_with_a_call_in_it():
    assert variants(SOURCE.replace('        i += 2;\n', '        i += 2;\n        use(i);\n'), 'lerp') == []


def test_registry_declares_the_family():
    assert any(FAMILY in repair.families for repair in registry.declared())
