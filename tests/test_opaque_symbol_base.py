"""A run of byte stores around one symbol, through a base pointer cse cannot fold back into the symbol."""
from decomprepair import opaque_symbol_base as p
from decomprepair import registry

SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern s8 flag_a;
extern u8 flag_b;
extern s8 palette;
extern f32 scale;

void reset(void) {
    M2C_FIELD(&palette, s8 *, -1) = 0;
    M2C_FIELD(&palette, s8 *, -3) = 0;
    M2C_FIELD(&palette, s8 *, -2) = 0;
    M2C_FIELD(&palette, s8 *, 2) = 0;
    M2C_FIELD(&palette, s8 *, 1) = 0;
    M2C_FIELD(&palette, s8 *, 0) = 0;
    M2C_FIELD(&palette, s8 *, 3) = 0xFF;
    flag_a = 0;
    scale = 0.0f;
}
'''

ASM = '''glabel reset
lui $v0, %hi(palette)
addiu $v0, $v0, %lo(palette)
sb $zero, -0x1($v0)
sb $zero, -0x3($v0)
sb $zero, 0x2($v0)
sb $v1, 0x3($v0)
'''


def test_the_run_becomes_a_base_pointer_with_a_term_only_the_combiner_can_zero():
    children = p.variants(SOURCE, 'reset', ASM)
    assert children and all(family == p.FAMILY for family, _ in children)
    text = children[0][1]
    assert 'u8 *base = (u8 *)&palette + (flag_b >> 8);' in text
    for k in (-1, -3, -2, 2, 1, 0, 3):
        assert f'base[{k}] = ' in text
    assert 'base[3] = 0xFF;' in text
    assert 'M2C_FIELD(&palette' not in text
    assert 'flag_a = 0;' in text


def test_a_signed_carrier_is_cast_to_unsigned_before_the_shift():
    assert any('(u8)flag_a >> 8' in text for _, text in p.variants(SOURCE, 'reset', ASM))


def test_the_cast_spelling_of_the_same_store_counts():
    source = SOURCE
    for k in (-1, -3, -2, 2, 1, 0, 3):
        source = source.replace(f'M2C_FIELD(&palette, s8 *, {k})', f'(*(s8 *)((s8 *)&palette + ({k})))')
    text = p.variants(source, 'reset', ASM)[0][1]
    assert 'base[-3] = 0;' in text and 'base[3] = 0xFF;' in text


def test_it_needs_the_targets_base_register():
    assert p.variants(SOURCE, 'reset', 'glabel reset\nlui $at, %hi(palette)\nsb $zero, %lo(palette)($at)\n') == []
    assert p.variants(SOURCE, 'reset', '') == []


def test_a_short_run_or_a_volatile_function_is_left_alone():
    short = SOURCE.replace('    M2C_FIELD(&palette, s8 *, 3) = 0xFF;\n', '').replace('    M2C_FIELD(&palette, s8 *, 0) = 0;\n', '') \
        .replace('    M2C_FIELD(&palette, s8 *, 1) = 0;\n', '').replace('    M2C_FIELD(&palette, s8 *, 2) = 0;\n', '')
    assert p.variants(short, 'reset', ASM) == []
    assert p.variants(SOURCE.replace('void reset(void) {', 'void reset(void) {\n    volatile int v;'), 'reset', ASM) == []


def test_no_byte_global_to_carry_the_term_means_no_child():
    assert p.variants(SOURCE.replace('extern s8 flag_a;\nextern u8 flag_b;\n', '').replace('flag_a = 0;', 'scale = 1.0f;'), 'reset', ASM) == []


def test_it_declares_itself_to_the_registry():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'opaque_symbol_base')) == []
