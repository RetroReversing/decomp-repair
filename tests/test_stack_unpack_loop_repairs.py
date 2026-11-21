"""m2c's pointer-walk unpacker, written back as the indexed loop over stack arrays."""
from decomprepair import stack_unpack_loop_repairs as x

# A homemade record unpacker of the same shape (not any game's code): a 2-byte header, then 4 records of 3 bytes into
# a[4] (5 bits), b[4] (3 bits) and e[8] (two 4-bit fields each), the arrays handed to a callee with six arguments.
SOURCE = '''s32 g();

s32 f(s32 arg0, void *arg1, s32 arg2) {
    u8 temp_t4;
    s32 sp28;
    s16 sp30;
    s16 sp38;
    s16 sp48;
    s16 sp4A;
    s32 *var_a;
    s32 *var_b;
    s32 *var_e;
    void *var_src;

    var_src = arg1;
    sp48 = (*(u8 *)((char *)(arg1) + 0)) >> 2;
    sp4A = (*(u8 *)((char *)(arg1) + 1)) & 0x3F;
    var_a = &sp28;
    var_b = &sp30;
    var_e = &sp38;
    loop: {
        var_a += 2;
        temp_t4 = (*(u8 *)((char *)(var_src) + 2));
        var_src += 3;
        *(s16 *)((char *)(var_a) + -2) = (s16) (temp_t4 >> 3);
        *(s16 *)var_b = (s16) ((*(u8 *)((char *)(var_src) + -1)) & 7);
        var_b += 2;
        *(s16 *)((char *)(var_e) + 2) = (s16) ((*(u8 *)((char *)(var_src) + 0)) & 0xF);
        *(s16 *)var_e = (s16) ((*(u8 *)((char *)(var_src) + 0)) >> 4);
        var_e += 4;
    }
    if (var_a != &sp30) goto loop;
    g(arg0, &sp48, &sp28, &sp30);
    return 0;
}
'''
ASM = '''addiu      $sp, $sp, -0x70
sw         $ra, 0x1C($sp)
sw         $a0, 0x70($sp)
sw         $a2, 0x78($sp)
addiu      $t5, $sp, 0x38
sw         $t5, 0x10($sp)
lw         $t8, 0x78($sp)
lw         $a0, 0x70($sp)
addiu      $a1, $sp, 0x48
addiu      $a2, $sp, 0x28
addiu      $a3, $sp, 0x30
jal        g
sw         $t8, 0x14($sp)
'''


def test_the_walk_becomes_an_indexed_loop():
    (family, plain), (_, swapped) = x.variants(SOURCE, 'f', ASM)
    assert family == 'stack_unpack_loop'
    for text in (plain, swapped):
        assert 'for (i = 0; i < 4; i++) {' in text
        assert 'u8 *arg1' in text and 'var_' not in text and 'goto' not in text and 'temp_t4' not in text
        # arrays from the objects' offsets, highest first; each runs to the next object
        assert text.index('s16 sp48[2];') < text.index('s16 sp38[8];') < text.index('s16 sp30[4];') < text.index('s16 sp28[4];')
        assert 'sp28[i]' in text and 'sp38[i*2]' in text and 'sp38[i*2+1]' in text and 'sp30[i]' in text
        assert 'arg1[i*3+2]' in text and 'arg1[i*3+3]' in text and 'arg1[0]' in text and 'sp48[1]' in text
        # the callee's stack arguments the draft never had come from the target's stores to their slots
        assert 'g(arg0, sp48, sp28, sp30, sp38, arg2);' in ' '.join(text.split()).replace(' ,', ',')


def test_stores_to_one_array_are_listed_by_ascending_index():
    text = x.variants(SOURCE, 'f', ASM)[0][1]
    assert text.index('sp38[i*2]') < text.index('sp38[i*2+1]')  # the draft stored element 1 first


def test_a_swapped_variant_puts_the_second_operand_first():
    both = x.variants(SOURCE.replace('(s16) (temp_t4 >> 3);', '(s16) ((temp_t4 >> 3) | (arg2 & 1));'), 'f', ASM)
    assert any('(arg2 & 1) | ' in t for _, t in both) and any('| (arg2 & 1)' in t for _, t in both)


def test_left_alone_otherwise():
    assert x.variants(SOURCE, 'f', '')[0][1]  # no target: the loop still becomes indexed, the call unchanged
    assert x.variants(SOURCE.replace('goto loop;', 'return 1;'), 'f', ASM) == []
    assert x.variants(SOURCE.replace('if (var_a != &sp30)', 'if (var_a != &sp34)'), 'f', ASM) == []  # not whole strides
    assert x.variants(SOURCE.replace('var_b += 2;', 'var_b += 2; g(var_b);'), 'f', ASM) == []  # a cursor escapes
    assert x.variants('void h(void) {}', 'f', ASM) == []


def test_m2cs_field_macro_and_typed_cursors_are_read_too():
    # what m2c writes today: M2C_FIELD(...) reads, `M2C_UNK *` cursors for the stores it can't type, a typed cursor read
    # as `*cursor`, and `do { } while (...)`; the cast chain above is the same program written out
    import re
    macro = re.sub(r'\(\*\((\w+) \*\)\(\(char \*\)\((\w+)\) \+ (-?\w+)\)\)', r'M2C_FIELD(\2, \1 *, \3)', SOURCE)
    macro = macro.replace('s32 *var_b;', 's16 *var_b;').replace('*(s16 *)var_b = ', '*var_b = ')
    macro = macro.replace('    loop: {', '    do {').replace('    }\n    if (var_a != &sp30) goto loop;', '    } while (var_a != &sp30);')
    assert 'M2C_FIELD(arg1, u8 *, 1)' in macro and '*var_b = ' in macro and 'do {' in macro
    for source in (macro, macro.replace('s32 *var_a;', 'M2C_UNK *var_a;')):
        found = x.variants(source, 'f', ASM)
        assert len(found) == 2 and 'sp30[i]' in found[0][1] and 'sp38[i*2+1]' in found[0][1]
        assert 'for (i = 0; i < 4; i++)' in found[0][1] and 'var_' not in found[0][1] and 'M2C_FIELD(var' not in found[0][1]
