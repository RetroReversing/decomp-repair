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
