from decomprepair.kmc_operand_repairs import mask_evidence, variants

# The target's `and` has the mask register first; the candidate's has the loaded value first.
SWAPPED = [(' ', 'lw $v1, 0x58($s0)', 'lw $v1, 0x58($s0)'),
           (' ', 'addiu $v0, $zero, -0x1c1', 'addiu $v0, $zero, -0x1c1'),
           ('r', 'and $v0, $v0, $v1', 'and $v0, $v1, $v0')]
SAME = [(' ', 'and $v0, $v1, $v0', 'and $v0, $v1, $v0')]

# The search's own dialect: a printed local holding the mask, applied with `&=` to a value loaded before it.
SAVED = '''void *f(void *arg0) {
    u32 *flags = (u32 *)((u8 *)arg0 + 0x58);
    u32 old = *flags;
    u32 updated = ~0x1c0U;
    updated &= old;
    *flags = updated;
    return arg0;
}'''


def texts(source, rows=SWAPPED, header=''):
    return [text for family, text in variants(source, 'f', header, rows) if family == 'mask_operand_order']


def test_mask_kept_in_a_local_is_hidden_behind_an_identity():
    [result] = texts(SAVED)
    assert 'u32 updated = ((old & ~0x1c0U) | ~0x1c0U);' in result
    assert 'updated &= old;' in result


def test_compound_and_expression_masks_are_rewritten_in_place():
    compound = 'void f(unsigned *p) { unsigned v = *p; v &= ~0x1c0; *p = v; }'
    [result] = texts(compound)
    assert 'v &= ((v & ~0x1c0) | ~0x1c0);' in result
    expression = 'unsigned f(unsigned v) { return v & 0xFFFFFE3F; }'
    [result] = texts(expression)
    assert 'return v & ((v & 0xFFFFFE3F) | 0xFFFFFE3F);' in result
    first = 'unsigned f(unsigned v) { return -449 & v; }'
    [result] = texts(first)
    assert 'return ((v & -449) | -449) & v;' in result


def test_needs_the_swapped_and_row_and_a_mask_that_needs_a_register():
    assert mask_evidence(SWAPPED) and not mask_evidence(SAME)
    assert not texts(SAVED, SAME)
    # 0xFF fits `andi`: the compiler never puts it in a register, so there is no operand order to move.
    assert not texts('unsigned f(unsigned v) { return v & 0xFF; }')
    assert not texts('unsigned f(unsigned v) { return v & 0xFFFF; }')


def test_refuses_what_it_cannot_prove_equivalent():
    assert not texts('unsigned f(unsigned *p) { return p[next()] & ~0x1c0; }')
    assert not texts('unsigned f(volatile unsigned v) { return v & ~0x1c0; }')
    assert not texts('unsigned f(unsigned v) { return v & ~0x1c0; }', header='#define v read()')
    # The identity reads a value defined after the mask: not in scope yet.
    late = 'unsigned f(unsigned v) { unsigned t = ~0x1c0; unsigned w = v; t &= w; return t; }'
    assert not texts(late)


M2C = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void f(void *arg0) {
    M2C_FIELD(arg0, s32 *, 0x58) = (s32) (-0x1C1 & M2C_FIELD(arg0, s32 *, 0x58));
}'''
# Registers all differ (the other allocation cluster): only the target's own `and` says the mask is first.
TARGET_FIRST = [(' ', 'lw $v1, 0x58($s0)', 'lw $v0, 0x58($s0)'), ('r', 'addiu $v0, $zero, -0x1c1', 'addiu $v1, $zero, -0x1c1'),
                (' ', 'and $v0, $v0, $v1', 'and $v0, $v0, $v1')]
TARGET_SECOND = [(' ', 'addiu $v1, $zero, -0x1c1', 'addiu $v1, $zero, -0x1c1'), (' ', 'and $v0, $v0, $v1', 'and $v0, $v0, $v1')]


def test_m2c_field_reads_are_pure_and_the_drafts_mask_first_form_is_rewritten():
    [result] = texts(M2C, rows=TARGET_FIRST)
    reads = 'M2C_FIELD(arg0, s32 *, 0x58)'
    assert f'(s32) ((({reads} & -0x1C1) | -0x1C1) & {reads});' in result
    # any other macro, or a different definition of the field macro, is not known to be pure
    assert not texts(M2C.replace('(s8 *)', '(char *)'), rows=TARGET_FIRST)
    assert not texts(M2C.replace('& M2C_FIELD(arg0, s32 *, 0x58)', '& M2C_FIELD(next(), s32 *, 0x58)'), rows=TARGET_FIRST)


def test_the_targets_own_and_is_evidence_even_when_every_register_differs():
    assert mask_evidence(TARGET_FIRST)
    assert not mask_evidence(TARGET_SECOND)  # the mask is the second operand: cse's order, nothing to hide


def test_a_macro_elsewhere_in_the_function_does_not_block_the_rewrite():
    # Drafts call NULL and friends everywhere; only a macro inside the read or the mask makes the identity unsafe.
    source = M2C.replace('{', '{ if (arg0 != NULL) ', 1).replace(';\n}', '; }\n}')
    [result] = texts(source, rows=TARGET_FIRST, header='#define NULL ((void *)0)')
    assert '((M2C_FIELD(arg0, s32 *, 0x58) & -0x1C1) | -0x1C1)' in result
    assert not texts('unsigned f(unsigned v) { return v & MASK; }', header='#define MASK 0xFFFFFE3F')
    assert not texts('unsigned f(unsigned v) { return v & ~0x1c0; }', header='#define v read()')
