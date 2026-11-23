import pytest

from decomprepair import registry
from decomprepair.quotient_chain_stage import FAMILY, variants

SOURCE = """void setup(u32 *rate, s32 ms) {
    s32 temp_v0;
    s32 size;
    s32 total;
    temp_v0 = *rate;
    if (ms != 0) {
        total = ((((((u32) temp_v0) * ms) / 1000) >> 6) / 3) * 0xC0; size = total + 0xC0;
        pending = 0;
    }
}"""
ASM = """lui $v0, (0x10624DD3 >> 16)
multu $v1, $v0
lui $v0, (0xAAAAAAAB >> 16)"""


def test_stages_the_first_quotient_and_moves_the_shift_after_the_second_division():
    [(family, source)] = variants(SOURCE, 'setup', ASM)
    assert family == FAMILY
    assert 'u32 __repair_quotient;' in source
    assert '__repair_quotient = (((u32) temp_v0) * ms) / 1000;' in source
    assert 'total = (((__repair_quotient / 3) >> 6)) * 0xC0;' in source
    assert source.index('__repair_quotient = ') < source.index('total = ')


def test_unsigned_variable_dividend_is_accepted():
    source = SOURCE.replace('(u32) temp_v0', 'count').replace('s32 temp_v0;', 'u32 count;')
    [(_, staged)] = variants(source, 'setup', ASM)
    assert '__repair_quotient = ((count) * ms) / 1000;' in staged


@pytest.mark.parametrize('source', [
    SOURCE.replace('(u32) temp_v0', 'temp_v0'),  # signed operands: the shift and the division do not commute
    SOURCE.replace('>> 6) / 3', '>> 6)'),
    SOURCE.replace('total = ', 'if (total > ('),
])
def test_refuses_signed_or_other_shapes(source):
    assert variants(source, 'setup', ASM) == []


def test_requires_both_magic_multiplies_in_the_target():
    assert variants(SOURCE, 'setup', ASM.replace('0xAAAAAAAB', '0xAAAAAAAC')) == []
    assert variants(SOURCE, 'setup', ASM.replace('0x10624DD3', '0x10624DD4')) == []


def test_is_declared_for_the_registry():
    [repair] = [r for r in registry.declared() if r.module == 'quotient_chain_stage']
    assert registry.problems(repair) == []
