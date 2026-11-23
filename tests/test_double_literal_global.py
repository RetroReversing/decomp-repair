"""double_literal_global: a double global read only as the literal its eight bytes hold, from the caller's data."""
import struct

from decomprepair import double_literal_global as dlg
from decomprepair import registry

SOURCE = '''extern f64 D_800D2EF0;
extern f64 D_800D2EF8;
extern f32 gScale;

void f(f32 *out, s32 arg1)
{
    f32 temp_fv0;

    temp_fv0 = (f32) ((f64) (f32) arg1 + D_800D2EF0);
    out[0] = temp_fv0 * gScale;
    out[1] = (f32) (D_800D2EF8 * 2.0);
}
'''
ASM = '''glabel f
/* 0 80001000 3C018010 */  lui        $at, %hi(D_800D2EF0)
/* 4 80001004 D4220000 */  ldc1       $ft3, %lo(D_800D2EF0)($at)
/* 8 80001008 3C028010 */  lui        $v0, %hi(D_800D2EF8)
/* C 8000100C D4440000 */  ldc1       $ft4, %lo(D_800D2EF8)($v0)
'''
HALF = struct.unpack('>Q', struct.pack('>d', 0.5))[0]
THIRD = struct.unpack('>Q', struct.pack('>d', 1.0 / 3.0))[0]


def test_a_double_read_through_the_literal_pool_becomes_the_literal():
    out = dlg.variants(SOURCE, 'f', asm=ASM, words={'D_800D2EF0': HALF, 'D_800D2EF8': HALF})
    assert len(out) == 1  # D_800D2EF8 is a real global: loaded through $v0, not $at
    family, child = out[0]
    assert family == 'double_literal_global'
    assert '(f64) (f32) arg1 + 0.5)' in child
    assert 'D_800D2EF8 * 2.0' in child


def test_the_literal_is_the_shortest_that_gives_the_same_eight_bytes_back():
    assert dlg.literal(HALF) == '0.5'
    assert dlg.literal(THIRD) == repr(1.0 / 3.0)
    assert dlg.literal(struct.unpack('>Q', struct.pack('>d', -2.0))[0]) == '(-2.0)'
    assert dlg.literal(struct.unpack('>Q', struct.pack('>d', 3.0))[0]) == '3.0'


def test_zero_a_pointer_and_a_denormal_are_not_literals():
    assert dlg.literal(0) is None
    assert dlg.literal(0x80123456) is None  # a denormal double: a pointer or an integer
    assert dlg.literal(0x7FF0000000000000) is None  # inf


def test_nothing_is_proposed_without_the_words_or_the_assembly_or_for_a_float_global():
    assert dlg.variants(SOURCE, 'f', asm=ASM) == []
    assert dlg.variants(SOURCE, 'f', words={'D_800D2EF0': HALF}) == []
    assert dlg.variants(SOURCE, 'f', asm=ASM, words={'gScale': HALF}) == []


def test_a_symbol_another_function_names_or_the_function_writes_is_left_alone():
    other = SOURCE + '\nvoid g(void)\n{\n    s32 v;\n\n    v = D_800D2EF0;\n}\n'
    assert dlg.variants(other, 'f', asm=ASM, words={'D_800D2EF0': HALF}) == []
    written = SOURCE.replace('out[0] = temp_fv0 * gScale;', 'D_800D2EF0 = 1.0;')
    assert dlg.variants(written, 'f', asm=ASM, words={'D_800D2EF0': HALF}) == []


def test_the_module_declares_itself_to_the_registry():
    repair = next(r for r in registry.declared() if r.module == 'double_literal_global')
    assert 'words' in repair.needs and repair.archs == ('mips',)


PAIR_SOURCE = '''extern f64 D_800D47F8;
extern f64 D_800D4800;

void f(f32 *out)
{
    f64 phase;

    phase = D_800D47F8;
    out[0] = (f32) (phase * D_800D4800);
}
'''
PAIR_ASM = '''glabel f
/* 0 80001000 3C01800D */  lui        $at, %hi(D_800D47F8)
/* 4 80001004 8C3447F8 */  lw         $s4, %lo(D_800D47F8)($at)
/* 8 80001008 8C3547FC */  lw         $s5, %lo(D_800D47FC)($at)
/* C 8000100C 3C01800D */  lui        $at, %hi(D_800D4800)
/* 10 80001010 D43E4800 */  ldc1       $fs5, %lo(D_800D4800)($at)
'''
TENTH = struct.unpack('>Q', bytes.fromhex('3FB9E83E425AEE63'))[0]


def test_a_double_held_in_two_general_registers_is_the_literal_gas_loads_as_two_words():
    # A 1133-instruction effect spawner, KMC GCC 2.7.2: the phase offset of a sine loop lives in $s4/$s5 across the
    # loop's calls; GAS's `li.d` loads it `lui $at; lw; lw` with the shared `$at` (a global read uses `lui $s4; lw $s4,
    # ($s4); lui $s5; ...`). As the literal: 610 -> 495, and 470 with the ldc1 doubles beside it.
    out = dlg.variants(PAIR_SOURCE, 'f', asm=PAIR_ASM, words={'D_800D47F8': TENTH, 'D_800D4800': THIRD})
    children = [child for _, child in out]
    assert any('phase = 0.1012;' in c and 'D_800D4800' in c.split('{', 1)[1] for c in children)
    assert any('phase = 0.1012;' in c and 'phase * 0.3333333333333333' in c for c in children)


def test_a_global_read_into_a_register_pair_or_an_indexed_table_is_not_a_literal():
    own = PAIR_ASM.replace('lui        $at, %hi(D_800D47F8)', 'lui        $s4, %hi(D_800D47F8)').replace(
        'lw         $s4, %lo(D_800D47F8)($at)', 'lw         $s4, %lo(D_800D47F8)($s4)')
    assert not dlg._double_loads('D_800D47F8', own)
    indexed = PAIR_ASM.replace('lui        $at, %hi(D_800D47F8)\n', 'lui        $at, %hi(D_800D47F8)\n'
                               '/* 2 80001002 00220821 */  addu       $at, $at, $v0\n')
    assert not dlg._double_loads('D_800D47F8', indexed)
    assert dlg._double_loads('D_800D47F8', PAIR_ASM)
