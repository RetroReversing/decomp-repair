"""A literal stored after a float-to-integer conversion, held in a local set before the float arithmetic."""
from decomprepair import constant_store_early_local as t

SOURCE = '''void f(void *arg0)
{
    f32 temp_fv1;
    s32 var_v1;
    void *rec;

    rec = *((void **) (((char *) arg0) + 0x490));
    temp_fv1 = (2.0f * height) - 44.0f;
    var_v1 = (u32) temp_fv1;
    *((s16 *) (((char *) rec) + 0x22)) = (s16) var_v1;
    *((s16 *) (((char *) rec) + 0x20)) = 0x20;
    g(rec);
}
'''


def test_the_literal_is_held_above_the_float_arithmetic_and_stored_first():
    # A 1133-instruction effect spawner: the `li` of the 0x20 store sat after the conversion's branches; held in a local
    # set before the float arithmetic (and stored before the converted value) it is the target's: 6120 -> 5630.
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert len(out) == 2
    stay, moved = out
    assert '  s32 cst_20;\n' in stay and 'cst_20 = 0x20;\n    temp_fv1 = (2.0f * height) - 44.0f;' in stay
    assert stay.index('+ 0x22)) = (s16) var_v1;') < stay.index('+ 0x20)) = cst_20;')
    assert moved.index('+ 0x20)) = cst_20;') < moved.index('+ 0x22)) = (s16) var_v1;')


def test_left_alone_otherwise():
    assert t.variants(SOURCE.replace('= 0x20;', '= 0;'), 'f') == []  # zero is $zero: no li
    assert t.variants(SOURCE.replace('    g(rec);\n', ''), 'f') != []
    assert t.variants(SOURCE.replace('(u32) temp_fv1', '(u32) other'), 'f') == []  # not a float conversion
    assert t.variants(SOURCE.replace('var_v1;\n    *((s16 *) (((char *) rec) + 0x20)) = 0x20;',
                                     'var_v1;\n    h();\n    *((s16 *) (((char *) rec) + 0x20)) = 0x20;'), 'f') == []  # a call


def test_it_declares_itself():
    from decomprepair import registry
    assert any(r.module == 'constant_store_early_local' for r in registry.declared())
