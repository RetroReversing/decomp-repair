"""unsigned_counter_float_cast: an unsigned local converted to float through the signed conversion."""
from decomprepair import registry
from decomprepair import unsigned_counter_float_cast as u

DRAFT = '''void f(f32 *out, u32 arg1)
{
    u32 var_t4;
    u32 var_t6;
    s32 signed_one;
    f32 temp_fv0;
    f32 temp_ft1;

    var_t4 = arg1;
    var_t6 = arg1 + 4;
    signed_one = 3;
    temp_fv0 = (f32) ((f64) (f32) var_t4 + D_800D2EF0);
    temp_ft1 = (f32) ((f64) (f32) var_t6 + D_800D2EF0);
    out[0] = temp_fv0 + (f32) signed_one;
    out[1] = temp_ft1 + (f32) var_t4;
}
'''


def test_every_unsigned_operand_of_a_float_cast_gets_the_signed_conversion_all_together_first():
    out = u.variants(DRAFT, 'f')
    assert [family for family, _ in out] == ['unsigned_counter_float_cast'] * 3
    both = out[0][1]
    assert both.count('(f32) (s32) var_t4') == 2 and '(f32) (s32) var_t6' in both
    assert '(f32) signed_one' in both and '(s32) signed_one' not in both
    assert '(f32) (s32) var_t6' not in out[1][1] or '(f32) (s32) var_t4' not in out[1][1]


def test_an_operand_already_cast_or_not_unsigned_is_left_alone():
    source = DRAFT.replace('(f32) var_t6', '(f32) (s32) var_t6').replace('(f32) var_t4', '(f32) signed_one')
    assert u.variants(source, 'f') == []


def test_the_module_declares_itself_to_the_registry():
    assert any(r.module == 'unsigned_counter_float_cast' for r in registry.declared())
