"""A string literal written as the target's symbol."""
from decomprepair import target_string_repairs as t

SOURCE = '''void f(void) {
    g(M2C_FIELD(D_80109BB0, s32 *, 0x18) + 0x28, "%s", h(0x10));
}
'''
ASM = 'lui        $a1, %hi(D_800D2AA0)\naddiu      $a1, $a1, %lo(D_800D2AA0)\nlw $v0, %lo(D_80109BB0)($v0)\n'


def test_the_literal_becomes_the_symbol():
    (family, out), = t.variants(SOURCE, 'f', ASM)
    assert family == 'target_string_symbol'
    assert 'extern char D_800D2AA0[];\nvoid f(void)' in out and ', D_800D2AA0, h(0x10));' in out


def test_left_alone_when_the_counts_differ():
    assert t.variants(SOURCE, 'f', 'lw $v0, %lo(D_80109BB0)($v0)\n') == []
    assert t.variants(SOURCE.replace('"%s"', '0'), 'f', ASM) == []


def test_verified_format_binding_handles_repeated_literal_and_requires_exact_rom_bytes():
    from decomprepair.target_string_repairs import verified_variants

    source = 'void f(void) { format(out, "%s %s", a, b); format(out, "%s %s", c, d); }'
    rows = [
        ('i', 'lui $a1, %hi(D_80001000)', 'lui $a1, %hi(?local)'),
        ('i', 'addiu $a1, $a1, %lo(D_80001000)', 'addiu $a1, $a1, %lo(?local)'),
    ] * 2
    verify = lambda code, evidence, data: verified_variants(code, 'f', '', evidence, data)
    [(family, candidate)] = verify(source, rows, lambda address, n: b'%s %s\0')
    assert family == 'verified_rom_string_symbol'
    assert candidate.startswith('extern const char D_80001000[];')
    assert candidate.count('format(out, D_80001000,') == 2
    assert not verify(source, rows[:2], lambda address, n: b'%s %s\0')
    assert not verify(source, rows, lambda address, n: b'%d %s\0')
    assert not verify(source, rows, lambda address, n: b'%s %sX')
