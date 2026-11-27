"""A masked call result through one carrier local for the argument and the result."""
from decomprepair import call_argument_carrier as m
from decomprepair import registry

SOURCE = '''s32 func_80044120();
s32 func_800449BC();
extern s32 D_80094270;
extern s32 D_8009427C;
extern s32 D_800AD450;

void f(void) {
    s32 temp_v0;

    temp_v0 = (func_800449BC((D_8009427C + 0xF) & ~0xF) + 0xF) & ~0xF;
    D_800AD450 = temp_v0;
    D_80094270 = (temp_v0 + 0x2DBF) & ~0xF;
    func_80044120(1);
}
'''


def test_the_argument_and_the_result_share_one_carrier_and_the_mask_goes_last():
    """An N64 allocator setup (KMC gcc 2.7.2 -O1 -g) was 20 inline and exact in the first child's form."""
    children = [child for family, child in m.variants(SOURCE, 'f')]
    assert len(children) == 2
    first = children[0]
    assert '    s32 carry;\n' in first
    assert ('    carry = (D_8009427C + 0xF) & ~0xF;\n    carry = func_800449BC(carry) + 0xF;\n'
            '    temp_v0 = carry & ~0xF;\n') in first
    assert '    carry = func_800449BC(carry);\n    temp_v0 = (carry + 0xF) & ~0xF;\n' in children[1]


def test_calls_with_several_arguments_or_side_effects_are_left_alone():
    assert m.variants(SOURCE.replace('func_800449BC((D_8009427C', 'func_800449BC(1, (D_8009427C'), 'f') == []
    assert m.variants(SOURCE.replace('(D_8009427C + 0xF)', '(g() + 0xF)'), 'f') == []
    assert m.variants(SOURCE.replace('& ~0xF) + 0xF) & ~0xF;', '& ~0xF) + 0xF);', 1), 'f') == []


def test_a_used_name_gets_another_carrier():
    child = m.variants(SOURCE.replace('s32 temp_v0;', 's32 temp_v0;\n    s32 carry;'), 'f')[0][1]
    assert 'carry2 = func_800449BC(carry2) + 0xF;' in child


def test_declared():
    assert registry.get('call_argument_carrier').families == (m.FAMILY,)
