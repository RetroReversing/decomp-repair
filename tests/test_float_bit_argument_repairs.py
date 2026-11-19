"""Float arguments m2c passed as bit patterns: back to float literals and an f32 parameter, under o32 only."""
from decomprepair import float_bit_argument_repairs as fba

O32 = ['-G0', '-mips3', '-mgp32', '-mfp32', '-O2']
SOURCE = '''s32 g(s32, s32, f32, void *);           /* extern */
s32 h(void *, s32, s32, s32);           /* extern */

void f(void *arg0, s32 arg1) {
    h(arg0, arg1, 0x3F000000, 1);
    g(0, 0x437A0000, 2.0f, arg0);
}
'''


def test_float_text_is_short_and_exact():
    assert fba.float_text(0x437A0000) == '250.0f'
    assert fba.float_text(0x3F000000) == '0.5f'
    assert fba.float_text(0x3DCCCCCD) == '0.1f'
    assert fba.float_text(0) == '0.0f'
    # small integers, NaN/inf, and bits that are no short float stay integers
    assert fba.float_text(1) is None and fba.float_text(0x7F800000) is None and fba.float_text(0x12345678) is None


def test_bits_become_a_float_literal_and_an_f32_parameter():
    # An N64 game (gcc 2.7.2 -O2): only `250.0f` to an f32 parameter scheduled its `lui $a1` first.
    outs = [out for family, out in fba.variants(SOURCE, 'f', '', 'mips', O32)]
    assert all(family == 'float_argument_bits' for family, _ in fba.variants(SOURCE, 'f', '', 'mips', O32))
    together, only_g, only_h = outs
    assert 's32 g(s32, f32, f32, void *);' in together and 's32 h(void *, s32, f32, s32);' in together
    assert 'h(arg0, arg1, 0.5f, 1);' in together and 'g(0, 250.0f, 2.0f, arg0);' in together
    assert 'h(arg0, arg1, 0x3F000000, 1);' in only_g and 'g(0, 250.0f, 2.0f, arg0);' in only_g
    assert 'g(0, 0x437A0000, 2.0f, arg0);' in only_h and 'h(arg0, arg1, 0.5f, 1);' in only_h


def test_named_parameters_keep_their_names():
    source = SOURCE.replace('s32 g(s32, s32, f32, void *);', 's32 g(s32 a, unsigned int b, f32 c, void *d);')
    out = next(o for _, o in fba.variants(source, 'f', '', 'mips', O32) if 'g(0, 250.0f' in o)
    assert 's32 g(s32 a, f32 b, f32 c, void *d);' in out


def test_left_alone_where_the_argument_would_move_or_change():
    def none(source=SOURCE, flags=O32, header='', arch='mips'):
        return not [o for _, o in fba.variants(source, 'f', header, arch, flags) if 'g(0, 250.0f' in o]
    assert none(flags=['-O2'])  # unknown ABI
    assert none(flags=O32 + ['-mabi=eabi']) and none(arch='ppc')  # floats in float registers
    assert none(SOURCE.replace('s32 g(s32, s32,', 's32 g(f32, s32,').replace('g(0,', 'g(0.0f,'))  # float first argument
    assert none(header='s32 g(s32, s32, f32, void *);')  # the header's prototype can't be retyped
    # another call passes a value that would be converted, not reinterpreted
    assert none(SOURCE.replace('    g(0, 0x437A0000', '    g(0, arg1, 2.0f, arg0);\n    g(0, 0x437A0000'))
    assert none(SOURCE.replace('0x437A0000', '7'))  # a small integer, not a float's bits
    assert none(SOURCE.replace('s32 g(s32, s32, f32, void *);', 's32 g(s32, void *, f32, void *);'))  # a pointer


def test_propose_finds_the_family():
    from decomprepair.propose import propose
    report = propose(SOURCE, 'f', arch='mips', flags=O32, header='')
    assert any(p.module == 'float_bit_argument_repairs' and 'g(0, 250.0f' in p.source for p in report.proposals)


def test_a_sole_float_parameter():
    """An N64 function called f(0x3F800000) where the game passed 1.0f in $f12: alone, a float first argument moves
    nothing else."""
    from decomprepair import float_bit_argument_repairs as fb
    source = 'f32 g(M2C_UNK);\nvoid f(void) {\n    D = g(0x3F800000) + 0.25f;\n}\n'
    (_, out), = fb.variants(source, 'f', '', 'mips', ['-mgp32'])
    assert 'f32 g(f32);' in out and 'g(1.0f)' in out


UNLISTED = '''f32 g();

void f(f32 *p) {
    p[0] = p[0] + g(0x3CA3D70A);
    p[1] = p[1] + g(0x3CA3D70A);
    p[2] = p[2] + g((short)0x3CA3D70A);
}
'''


def test_an_unlisted_prototype_and_a_leftover_cast():
    # An N64 function at 80.1%: m2c's `f32 g();` with the bits of 0.02f, one call carrying a permuter's
    # `(short)` cast (which never reached the register: the target loads all 32 bits); 84.9% with `g(0.02f)`.
    from decomprepair import float_bit_argument_repairs as fb
    (family, out), = fb.variants(UNLISTED, 'f', flags=['-mgp32'])
    assert 'f32 g(f32);' in out and out.count('g(0.02f)') == 3 and '0x3CA3D70A' not in out


def test_an_unlisted_prototype_keeps_its_other_arguments_integer():
    from decomprepair import float_bit_argument_repairs as fb
    source = UNLISTED.replace('g(0x3CA3D70A)', 'g(1, 0x3CA3D70A)').replace('g((short)0x3CA3D70A)', 'g(2, 0x3CA3D70A)')
    (family, out), = fb.variants(source, 'f', flags=['-mgp32'])
    assert 'f32 g(s32, f32);' in out and 'g(2, 0.02f)' in out
    # calls that disagree on how many arguments there are leave it alone
    assert fb.variants(source.replace('g(2, 0x3CA3D70A)', 'g(0x3CA3D70A)'), 'f', flags=['-mgp32']) == []
