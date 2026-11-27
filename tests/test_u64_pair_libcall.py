"""m2c's two halves of a 64-bit multiply and divide, as the one expression."""
from decomprepair import registry
from decomprepair import u64_pair_libcall as pair

HEAD = '''extern s32 D_hi;
extern u32 D_lo;
void boot(void)
{
    s32 temp_ret;
    u32 temp_a1;

'''
SEPARATE = HEAD + '''    temp_a1 = D_lo * 3;
    temp_ret = func_div(((D_hi * 2) | ((u32) D_lo >> 0x1F)) + D_hi + (temp_a1 < (u32) D_lo), temp_a1, 0, 4);
    D_hi = temp_ret;
    D_lo = (u32) (u64) temp_ret;
}
'''
INLINE = HEAD + '''    temp_ret = func_div(((D_hi * 2) | ((u32) D_lo >> 0x1F)) + D_hi + ((temp_a1 = D_lo * 3) < (u32) D_lo), temp_a1, 0, 4);
    D_hi = temp_ret;
    D_lo = (u32) (u64) temp_ret;
}
'''


def children(source):
    found = pair.variants(source, 'boot')
    assert all(family == pair.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_both_spellings_of_the_low_product_give_the_one_expression():
    for source in (SEPARATE, INLINE):
        retyped, modulo, cast, _ = children(source)
        assert '    D_hi = D_hi * 3 / 4ULL;\n' in retyped
        assert 'extern unsigned long long D_hi;' in retyped and 'D_lo' not in retyped
        assert 'temp_a1' not in retyped and 'temp_ret' not in retyped
        assert '% 4ULL' in modulo
        assert '*(unsigned long long *) &D_hi = *(unsigned long long *) &D_hi * 3 / 4ULL;' in cast


def test_a_low_half_named_elsewhere_keeps_its_declaration():
    found = children(SEPARATE.replace('    temp_a1 = D_lo * 3;', '    use(D_lo);\n    temp_a1 = D_lo * 3;'))
    assert found and all('extern u32 D_lo;' in text for text in found)


def test_a_result_read_again_is_left_alone():
    assert children(SEPARATE.replace('(u64) temp_ret;\n}', '(u64) temp_ret;\n    use(temp_ret);\n}')) == []


def test_the_family_is_registered():
    assert any(pair.FAMILY in repair.families for repair in registry.declared())
