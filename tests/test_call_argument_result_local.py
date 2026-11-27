from decomprepair.call_argument_result_local import FAMILY, variants

SOURCE = '''s32 func_80042154();
s32 func_800449BC();
extern s32 D_80094270;
extern s32 D_80094278;

void f(s32 arg0, s32 arg1) {
    D_80094270 = (func_800449BC((D_80094278 + 7) & ~7) + 7) & ~7;
    func_80042154(arg0, arg1);
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_argument_and_result_share_one_local():
    """The exact child on an N64 function (KMC GCC 2.7.2 -O1 -g, 34 instructions): 20 -> 0."""
    (child,) = children()
    assert 's32 temp;' in child
    assert ('    temp = (D_80094278 + 7) & ~7;\n    temp = (func_800449BC(temp) + 7) & ~7;\n'
            '    D_80094270 = temp;\n') in child
    assert 'func_80042154(arg0, arg1);' in child


def test_the_store_type_is_the_global_s():
    (child,) = children(SOURCE.replace('extern s32 D_80094270;', 'extern u16 D_80094270;'))
    assert 'u16 temp;' in child


def test_left_alone():
    assert children(SOURCE.replace('(D_80094278 + 7) & ~7)', 'D_80094278)')) == []  # a plain name
    assert children(SOURCE.replace('+ 7) & ~7;\n', '+ 7) & g();\n')) == []  # a second call
    assert children(SOURCE.replace('(D_80094278 + 7)', '(D_80094278++)')) == []
