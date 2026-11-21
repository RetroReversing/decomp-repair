import re

import pytest

from decomprepair import draft_call_recovery, ido_packed_stack_word, ido_typed_loops

RECIPROCAL = '''
void f(f32 *src, void *dst) {
    f32 *s; f32 v; s32 row; void *d;
    s = src; row = 0; d = dst;
    do { row += 1; d += 0x10; v = 1.0f / *s; s += 0x10;
    M2C_FIELD(d, f32 *, -0x10) = v;
    M2C_FIELD(d, f32 *, -0xC) = (f32) (1.0f / M2C_FIELD(s, f32 *, -0xC));
    M2C_FIELD(d, f32 *, -8) = (f32) (1.0f / M2C_FIELD(s, f32 *, -8));
    M2C_FIELD(d, f32 *, -4) = (f32) (1.0f / M2C_FIELD(s, f32 *, -4)); } while (row != 4);
}
'''
VISITOR = '''
void f(void *widgets) {
    s32 n; void **instance; void *vtable; void *slots;
    n = 0; slots = widgets;
    if (M2C_FIELD(widgets, s32 *, 0x120) > 0) {
        do {
            instance = M2C_FIELD(slots, void ***, 0x134);
            vtable = *instance;
            M2C_FIELD(vtable, M2C_UNK (**)(void *), 0xC)(M2C_FIELD(vtable, s16 *, 8) + instance);
            n += 1;
            slots += 4;
        } while (n < M2C_FIELD(widgets, s32 *, 0x120));
    }
}
'''
RECORD = '''
void f(void *record, s32 type, u8 *letters, void *fields) {
    s32 step; s32 i; u8 *p; void *result; void *words; void *out;
    M2C_FIELD(record, s32 *, 0) = (s32) (type & 0xFF);
    i = 0; out = record; p = letters;
    do { i += 1; out += 1; M2C_FIELD(out, s8 *, 4) = (s8) (*p - 0x61); p += 1; } while (i != 3);
    step = 1 * 4; words = fields + step;
    M2C_FIELD(record, s32 *, 8) = (s32) M2C_FIELD(fields, s32 *, 4);
    result = record + step;
    M2C_FIELD(result, s32 *, 8) = (s32) M2C_FIELD(words, s32 *, 4);
    M2C_FIELD(result, s32 *, 0xC) = (s32) M2C_FIELD(words, s32 *, 8);
    M2C_FIELD(result, s32 *, 0x10) = (s32) M2C_FIELD(words, s32 *, 0xC);
    M2C_FIELD(result, s32 *, 0x14) = (s32) M2C_FIELD(words, s32 *, 0x10);
    M2C_FIELD(record, s8 *, 4) = 5; M2C_FIELD(record, s32 *, 0x1C) = (s32) M2C_FIELD(fields, s32 *, 0);
}
'''


def with_labels(normalized):
    """Render the compiler schedule with unrelated synthetic addresses."""
    base = 0x80100DB0
    labels = {int(index): f'.L{base + int(index) * 4:08X}' for index in re.findall(r'@(\d+)', normalized)}
    result = []
    for i, insn in enumerate(normalized.splitlines()):
        if i in labels:
            result.append(labels[i] + ':')
        result.append(re.sub(r'@(\d+)', lambda match: labels[int(match[1])], insn))
    return '\n'.join(result)


@pytest.mark.parametrize(('family', 'source', 'expected'), [
    ('ido_reciprocal_matrix', RECIPROCAL, '_m2c_typed_out = dst, _m2c_typed_in = src'),
    ('ido_typed_virtual_visitor', VISITOR, '_m2c_typed_index < widgets[0x120 / 4]'),
    ('ido_typed_record_copy', RECORD, 'record[_m2c_typed_word + 2] = fields[_m2c_typed_word + 1]'),
])
def test_typed_loop_candidates_keep_the_measured_cursor_shape(family, source, expected):
    target = with_labels(next(text for text, shape in ido_typed_loops._TARGETS.items() if shape[0] == family))
    [(kind, fixed)] = draft_call_recovery.baseline_variants(source, 'f', target, '', 'ido-7.1')
    assert kind == family and expected in fixed
    assert not ido_typed_loops.variants(source, 'f', target, 'void f();')
    assert not ido_typed_loops.variants(source, 'f', target.replace('jr $ra', 'jr $t0'))
    assert not ido_typed_loops.variants(source.replace('M2C_FIELD', 'OTHER_FIELD'), 'f', target)


STACK_WORD_ASM = '''
addiu $sp, $sp, -48
sw $a0, 48($sp)
lw $t6, 48($sp)
sw $a1, 52($sp)
lw $t4, 52($sp)
sll $t7, $t6, 26
sw $zero, 40($sp)
sra $t8, $t7, 26
lb $t1, 40($sp)
sll $t9, $t8, 2
lb $t8, 41($sp)
sll $t5, $t4, 27
andi $t0, $t9, 252
sra $t6, $t5, 27
andi $t2, $t1, 65283
andi $t7, $t6, 31
andi $t9, $t8, 65504
or $t3, $t0, $t2
or $t1, $t7, $t9
sw $ra, 20($sp)
sb $t3, 40($sp)
sb $t1, 41($sp)
lui $a0, (0x04002200 >> 16)
ori $a0, $a0, (0x04002200 & 65535)
jal write_word
lw $a1, 40($sp)
lui $a0, (0x04970000 >> 16)
jal write_word
or $a1, $zero, $zero
lw $ra, 20($sp)
addiu $sp, $sp, 48
jr $ra
nop
'''
STACK_WORD_C = '''
void f(s32 left, s32 right) {
    s32 sp28;
    sp28 = 0;
    sp28 = ((((s32) (left << 0x1A) >> 0x1A) * 4) & 0xFC) | ((s8) sp28 & 0xFF03);
    unksp29 = (((s32) (right << 0x1B) >> 0x1B) & 0x1F) | (unksp29 & 0xFFE0);
    write_word(0x04002200, (s32) sp28);
    write_word(0x04970000, 0);
}
'''


@pytest.mark.parametrize('third_field', [False, True])
def test_packed_word_requires_the_witnessed_byte_slices(third_field):
    source, asm = STACK_WORD_C, STACK_WORD_ASM
    if third_field:
        source = source.replace('    write_word(0x04002200', '    unksp2A = (unksp2A & 0xFF07) | 0x20;\n    write_word(0x04002200')
        asm = asm.replace('lui $a0, (0x04002200', 'lb $t0, 42($sp)\nandi $t2, $t0, 65287\nori $t3, $t2, 32\nsb $t3, 42($sp)\nlui $a0, (0x04002200')
    [(family, fixed)] = draft_call_recovery.variants(source, 'f', asm, '', 'ido-7.1')
    assert family == ido_packed_stack_word.FAMILY
    assert 'union {' in fixed and 'write_word(0x04002200, _m2c_packed_word.value)' in fixed
    assert ('bits.z = 4;' in fixed) == third_field
    assert not ido_packed_stack_word.rewrite(source, 'f', asm.replace('65283', '65280'))
    assert not ido_packed_stack_word.rewrite(source, 'f', asm.replace('lw $a1, 40', 'lw $a1, 44'))
    assert not ido_packed_stack_word.rewrite(source, 'f', asm, 'extern int unksp29;')
