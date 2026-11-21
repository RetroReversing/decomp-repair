from decomprepair import draft_call_recovery
from decomprepair import ido_cursor_drafts as repairs


def annotate(text, labels=None):
    labels = labels or {}
    return '\n'.join(f'{labels.get(i, "")}/* {i*4:06X} {0x80000000+i*4:08X} 00000000 */ {op}'
                     for i, op in enumerate(text.splitlines()))


def test_signed_word_uses_two_postincrement_loads():
    source = '''s16 f(void **ptr) {
    void *p;
    void *q;
    p = *ptr;
    q = p + 1;
    *ptr = q;
    *ptr = q + 1;
    return (s16) (M2C_FIELD(p, u8 *, 1) | (s16) (M2C_FIELD(p, u8 *, 0) << 8));
}
'''
    asm = annotate(repairs._WORD_ASM)
    [(family, fixed)] = draft_call_recovery.variants(source, 'f', asm, '', 'ido-7.1')
    assert family == 'initial_ido_word_cursor'
    assert 'f(u8 **ptr)' in fixed and fixed.count('*(*ptr)++') == 2
    assert not draft_call_recovery.variants(source, 'f', asm, '', 'gcc-2.7.2-kmc')
    assert not repairs.variants(source.replace('q + 1;', 'q + 2;'), 'f', asm)
    assert not repairs.variants(source, 'f', asm.replace('sra $v0, $v1, 16', 'srl $v0, $v1, 16'))
    assert not repairs.variants(source, 'f', asm, 's16 f(void **ptr);')


def test_variable_width_cursor_preserves_the_wide_return():
    source = '''u8 f(void **ptr) {
    u8 result;
    void *next;
    void *first;
    first = *ptr;
    result = M2C_FIELD(first, u8 *, 0);
    next = first + 1;
    *ptr = next;
    if (result & 0x80) {
        result = (M2C_FIELD(first, u8 *, 1) | ((result << 8) & 0x7F00)) & 0xFFFF;
        *ptr = next + 1;
    }
    return result;
}
'''
    asm = annotate(repairs._COMPRESSED_ASM, {14: '.Lexit:\n'})
    [(family, fixed)] = repairs.variants(source, 'f', asm)
    assert family == 'initial_ido_variable_word_cursor'
    assert 's32 f(u8 **ptr)' in fixed
    assert fixed.count('while (0)') == 2
    assert not repairs.variants(source, 'f', annotate(repairs._COMPRESSED_ASM, {13: '.Lexit:\n'}))
    assert not repairs.variants(source, 'f', asm.replace('32512', '7936'))


def test_biased_copy_uses_word_formals_and_typed_cursors():
    source = '''void f(void *out, s8 a, s8 b, u8 *in, s32 x, s32 y, s32 z) {
    s32 index;
    u8 *src;
    void *dest;
    M2C_FIELD(out, s8 *, 0) = a;
    M2C_FIELD(out, s8 *, 1) = b;
    index = 0;
    dest = out;
    src = in;
    do {
        index += 1;
        dest += 1;
        M2C_FIELD(dest, s8 *, 1) = (s8) (*src - 0x61);
        src += 1;
    } while (index != 3);
    M2C_FIELD(out, s8 *, 5) = (s8) x;
    M2C_FIELD(out, s8 *, 6) = (s8) y;
    M2C_FIELD(out, s8 *, 7) = (s8) z;
}
'''
    asm = annotate(repairs._BIASED_ASM, {6: '.Lloop:\n'})
    [(family, fixed)] = repairs.variants(source, 'f', asm)
    assert family == 'initial_ido_biased_byte_copy'
    assert 'f(s8 *out, s32 a, s32 b,' in fixed
    assert 'dest[1] = *src - 0x61;' in fixed
    assert not repairs.variants(source, 'f', asm.replace('20($sp)', '24($sp)'))
    assert not repairs.variants(source, 'f', annotate(repairs._BIASED_ASM, {7: '.Lloop:\n'}))
    assert not repairs.variants(source.replace('dest += 1;', 'dest += 2;'), 'f', asm)
