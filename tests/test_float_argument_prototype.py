"""Float bits passed in integer registers: the callee's `f32` parameter and the float literal, read off the target."""
from decomprepair import float_argument_prototype as fap

PROFILE = ['-G0', '-mips3', '-O2', '-mfp64']  # no `-mgp32`: the target must say it
SOURCE = '''M2C_UNK h(M2C_UNK, M2C_UNK, M2C_UNK, M2C_UNK, s32, s32, s32); /* extern */
f32 g(f32, f32, M2C_UNK);               /* extern */

void f(void *arg0, f32 arg1) {
    h(0xA, 0x4542B000, 0x451EA000, 0x4423C000, 5, 6, 0);
    h(0xB, 0x4514D000, 0x448DC000, 0x45A40800, 7, 8, 0);
    arg1 = g(arg1, M2C_FIELD(arg0, f32 *, 8), 0x41A00000);
}
'''
ASM = '''
glabel f
    /* 0 */  lui        $a1, (0x4542B000 >> 16)
    /* 4 */  ori        $a1, $a1, (0x4542B000 & 0xFFFF)
    /* 8 */  lui        $a2, (0x451EA000 >> 16)
    /* c */  ori        $a2, $a2, (0x451EA000 & 0xFFFF)
    /* 10 */  lui        $a3, (0x4423C000 >> 16)
    /* 14 */  ori        $a3, $a3, (0x4423C000 & 0xFFFF)
    /* 18 */  addiu      $a0, $zero, 0xA
    /* 1c */  jal        h
    /* 20 */   sw        $zero, 0x18($sp)
    /* 24 */  addiu      $a0, $zero, 0xB
    /* 28 */  lui        $a1, (0x4514D000 >> 16)
    /* 2c */  ori        $a1, $a1, (0x4514D000 & 0xFFFF)
    /* 30 */  lui        $a2, (0x448DC000 >> 16)
    /* 34 */  ori        $a2, $a2, (0x448DC000 & 0xFFFF)
    /* 38 */  lui        $a3, (0x45A40800 >> 16)
    /* 3c */  ori        $a3, $a3, (0x45A40800 & 0xFFFF)
    /* 40 */  jal        h
    /* 44 */   sw        $zero, 0x18($sp)
    /* 48 */  lwc1       $fa1, 0x8($s0)
    /* 4c */  lui        $a2, (0x41A00000 >> 16)
    /* 50 */  jal        g
    /* 54 */   mov.s     $fa0, $fs0
endlabel f
'''


def texts(source=SOURCE, asm=ASM, flags=PROFILE, header='', arch='mips'):
    out = fap.variants(source, 'f', header, arch, asm, flags)
    assert all(family == 'float_argument_prototype' for family, _ in out)
    return [text for _, text in out]


def test_evidence_reads_the_constants_the_target_builds_for_each_call():
    seen = fap.evidence(ASM)
    assert seen['h'] == {1: {0x4542B000, 0x4514D000}, 2: {0x451EA000, 0x448DC000}, 3: {0x4423C000, 0x45A40800}}
    assert seen['g'] == {2: {0x41A00000}}  # (no ori: the low half is zero; $fa0/$fa1 are no argument registers here)


def test_integer_looking_floats_become_literals_and_f32_parameters():
    # A sn-n64 function (`-mips3 -O2`, no -mgp32): 60 -> 0 once all three of both calls were floats.
    everything, *rest = texts()
    assert 'M2C_UNK h(M2C_UNK, f32, f32, f32, s32, s32, s32);' in everything
    assert 'h(0xA, 3115.0f, 2538.0f, 655.0f, 5, 6, 0);' in everything and 'h(0xB, 2381.0f, 1134.0f, 5249.0f, 7, 8, 0);' in everything
    # and the float-first callee: both the prototype and the literal (the literal alone is converted by value)
    assert 'f32 g(f32, f32, f32);' in everything and 'g(arg1, M2C_FIELD(arg0, f32 *, 8), 20.0f);' in everything
    assert len(rest) <= 7 and len(set(texts())) == len(texts())
    only_g = next(t for t in rest if 'g(arg1, M2C_FIELD(arg0, f32 *, 8), 20.0f)' in t and '3115.0f' not in t)
    assert 'M2C_UNK h(M2C_UNK, M2C_UNK, M2C_UNK, M2C_UNK, s32, s32, s32);' in only_g


def test_one_position_alone_is_a_child():
    one = [t for t in texts() if 'h(M2C_UNK, f32, M2C_UNK' in t or 'h(M2C_UNK, M2C_UNK, f32, M2C_UNK' in t]
    assert one and all('3115.0f' in t or '2538.0f' in t for t in one)


def test_a_float_already_declared_needs_only_its_literal():
    source = SOURCE.replace('f32 g(f32, f32, M2C_UNK);', 'f32 g(f32, f32, f32);')
    assert any('20.0f)' in t for t in texts(source))


def test_the_explicit_o32_profile_stands_in_for_a_missing_assembly():
    assert not texts(asm='')  # nothing says the arguments are in integer registers
    assert texts(asm='', flags=['-mips3', '-mgp32', '-mfp32'])


def test_left_alone_without_evidence_or_where_the_argument_would_move():
    no_h = [t for t in texts(asm=ASM.replace('jal        h', 'jal        k')) if '3115.0f' in t]
    assert not no_h  # the target does not call h with those registers
    assert not [t for t in texts(asm=ASM.replace('0x4542B000', '0x4542B001')) if 'h(0xA, 3115.0f' in t]  # another value
    assert not texts(flags=PROFILE + ['-mabi=eabi']) and not texts(arch='ppc')
    assert not texts(header='M2C_UNK h(M2C_UNK, M2C_UNK, M2C_UNK, M2C_UNK, s32, s32, s32);' + '\nf32 g(f32, f32, M2C_UNK);')
    # a call passing a value that would be converted, not reinterpreted
    assert not [t for t in texts(SOURCE.replace('h(0xB, 0x4514D000', 'h(0xB, arg1')) if 'h(M2C_UNK, f32' in t]
    assert not [t for t in texts(SOURCE.replace('0x4542B000', '7')) if 'h(M2C_UNK, f32' in t]  # a small integer
    # the second argument after a float first one travels in $f14: its register would change
    moved = SOURCE.replace('M2C_UNK h(M2C_UNK, M2C_UNK,', 'M2C_UNK h(f32, M2C_UNK,').replace('h(0xA, 0x4542B000', 'h(0xA, 0x4542B000')
    assert not [t for t in texts(moved) if 'h(f32, f32' in t]
