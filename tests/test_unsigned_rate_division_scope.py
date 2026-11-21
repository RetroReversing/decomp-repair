import pytest

from decomprepair.unsigned_rate_division_scope import FAMILY, variants

SOURCE = """void update(int *rate, int frames) {
    if (frames != 0) {
        pending = 0;
        total = ((((((*rate) * frames) / 1000) >> 6) / 3) * 0xC0) + 0xC0;
    }
}"""
ASM = """lui $v0, (0x10624DD3 >> 16)
multu $v0, $a0
mfhi $v0
lui $v1, (0xAAAAAAAB >> 16)
multu $v0, $v1
sw $zero, %lo(pending)($a1)
mfhi $t0
srl $v1, $t0, 7"""


def test_stages_unsigned_quotient_before_reset():
    [(family, source)] = variants(SOURCE, 'update', 'mips', ASM, 'int __repair_rate_quotient;')
    assert family == FAMILY
    assert source.index('* frames) / 1000U') < source.index('pending = 0;')
    assert 'total = (__repair_rate_quotient_ / 192U) * 0xC0U + 0xC0U;' in source


@pytest.mark.parametrize('assembly', [
    ASM.replace('0x10624DD3', '0x10624DD4'),
    ASM.replace('%lo(pending)', '%lo(other)'),
    ASM.replace('srl $v1, $t0', 'srl $v1, $t1'),
])
def test_requires_target_division_and_reset(assembly):
    assert variants(SOURCE, 'update', 'mips', assembly) == []


def test_requires_original_grouping():
    assert variants(SOURCE.replace('>> 6) / 3', '>> 6 / 3)'), 'update', 'mips', ASM) == []
