"""clamp_zero_idiom: m2c's `a & ((s32) ~a >> 0x1F)` written as the compare."""
from decomprepair import clamp_zero_idiom as c
from decomprepair import registry

DRAFT = '''void f(u32 arg0, u32 arg1)
{
    s32 temp_a1;
    s32 temp_a2;
    s32 temp_t3;
    s32 temp_t4;
    u32 other;

    temp_a1 = arg0 - 1;
    temp_t3 = temp_a1 & ((s32) ~temp_a1 >> 0x1F);
    temp_a2 = arg1 - 1;
    temp_t4 = temp_a2 & ((s32) ~temp_a2 >> 0x1F);
    other = temp_t3 + temp_t4;
}
'''


def test_a_copy_and_its_mask_become_one_assignment_and_the_compare_all_sites_together_first():
    out = c.variants(DRAFT, 'f')
    assert [family for family, _ in out] == ['clamp_zero_idiom'] * 3
    both = out[0][1]
    assert 'temp_t3 = arg0 - 1; if (temp_t3 < 0) { temp_t3 = 0; }' in both
    assert 'temp_t4 = arg1 - 1; if (temp_t4 < 0) { temp_t4 = 0; }' in both
    assert '~' not in both and 'temp_a1' not in both and 'temp_a2' not in both
    assert 'temp_t4 = temp_a2 &' in out[1][1] and 'temp_t3 = arg0 - 1; if (' in out[1][1]


def test_the_in_place_form_and_an_unsigned_result_keep_the_sign_test():
    source = DRAFT.replace('s32 temp_t3;', 'u32 temp_t3;').replace(
        'temp_t3 = temp_a1 & ((s32) ~temp_a1 >> 0x1F);', 'temp_t3 = temp_t3 & ((s32) ~temp_t3 >> 0x1F);')
    out = c.variants(source, 'f')
    assert any('if ((s32) temp_t3 < 0) { temp_t3 = 0; }' in child for _, child in out)


def test_a_copy_read_elsewhere_is_left_alone():
    source = DRAFT.replace('other = temp_t3 + temp_t4;', 'other = temp_t3 + temp_a1;')
    out = c.variants(source, 'f')
    assert all('temp_t3 = temp_a1 &' in child for _, child in out if 'temp_t3 = arg0 - 1' not in child)
    assert not any('temp_t3 = arg0 - 1;' in child for _, child in out)


def test_the_module_declares_itself_to_the_registry():
    assert any(r.module == 'clamp_zero_idiom' for r in registry.declared())
