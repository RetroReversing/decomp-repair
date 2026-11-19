"""A load that is one operand of a sum, given its own statement before it."""
from decomprepair import expression_locals as e

SOURCE = '''void f(s32 arg0, void *arg1) {
    void *temp_v0;

    temp_v0 = (arg0 * 0x18) + M2C_FIELD(M2C_FIELD(arg1, void **, 0x6C), s32 *, 4);
    M2C_FIELD(arg1, f32 *, 0x24) = (f32) M2C_FIELD(temp_v0, f32 *, 0);
}
'''


def operands(source):
    return [text for family, text in e.variants(source, 'f') if family == 'operand_temporary']


def test_the_load_chain_comes_first():
    # An N64 function (gcc 2.7.2 -O2) at 89%: the index was scheduled between the two loads; exact this way.
    out, = operands(SOURCE)
    assert '\ns32 __repair_operand;\n' in out
    assert ('    __repair_operand = M2C_FIELD(M2C_FIELD(arg1, void **, 0x6C), s32 *, 4);\n'
            '    temp_v0 = (arg0 * 0x18) + __repair_operand;\n') in out


def test_only_loads_in_a_plain_statement():
    assert operands(SOURCE.replace('(arg0 * 0x18) + M2C_FIELD(', 'M2C_FIELD(')) == []  # not a sum
    assert operands(SOURCE.replace('M2C_FIELD(arg1, void **, 0x6C)', 'g(arg1)')) == []  # a call moves
    assert operands(SOURCE.replace('    temp_v0 = (arg0', '    for (temp_v0 = (arg0').replace('s32 *, 4);\n', 's32 *, 4);;) {}\n', 1)) == []


def test_propose_finds_it():
    from decomprepair.propose import propose
    assert any('__repair_operand = M2C_FIELD' in p.source for p in propose(SOURCE, 'f').proposals)


GLOBAL = '''extern s32 D_800E41DC;

void f(s32 arg0) {
    void *temp_a0;

    temp_a0 = (arg0 * 0x68) + D_800E41DC;
    M2C_FIELD(temp_a0, u16 *, 0x28) = 0x14U;
}
'''


def test_a_global_operand_comes_first():
    # An N64 function at 94.5% loaded the global before the index: exact this way.
    out, = [text for family, text in e.variants(GLOBAL, 'f') if family == 'operand_temporary']
    assert '\ns32 __repair_operand;\n' in out
    assert '    __repair_operand = D_800E41DC;\n    temp_a0 = (arg0 * 0x68) + __repair_operand;' in out
    assert [t for f, t in e.variants(GLOBAL.replace('    M2C_FIELD(temp_a0, u16 *, 0x28) = 0x14U;', '    D_800E41DC = 0;'), 'f')
            if f == 'operand_temporary'] == []  # the function changes it
