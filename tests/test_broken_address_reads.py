import pytest

from decomprepair import draft_call_recovery, heap_span_drafts, ido_mapped_poll

HEAP_TARGET = '''
glabel span
addu $v1, $a0, $zero
lbu $v0, -7($v1)
beqz $v0, .Lsingle
addiu $a0, $a0, -16
addiu $a0, $a0, 16
beqz $a0, .Ldone
addu $a1, $zero, $zero
.Lloop:
lbu $v0, 8($a0)
bnez $v0, .Lnext
nop
lw $v0, 0($a0)
addiu $v0, $v0, -16
{update}
.Lnext:
lw $a0, 0($a0)
beqz $a0, .Ldone
nop
j .Lloop
nop
.Lsingle:
lw $v0, -16($v1)
subu $v0, $v0, $a0
addiu $a1, $v0, -32
.Ldone:
jr $ra
addu $v0, $a1, $zero
endlabel span
'''
HEAP_DRAFT = '''
{ctype} span(void *start) {{
    {extra}
    {ctype} total;
    void *base;
    void *cursor;
    base = start - 0x10;
    if (M2C_FIELD(start, u8 *, -7) != 0) {{
        cursor = base + 0x10;
        total = 0;
        if (cursor != NULL) {{
loop_1:
            if (M2C_FIELD(cursor, u8 *, 8) == 0) {{
                {update}
            }}
            cursor = M2C_FIELD(cursor, void **, 0);
            if (cursor != NULL) {{
                goto loop_1;
            }}
        }}
    }} else {{
        total = (M2C_FIELD(start, s32 *, -0x10) - base) - 32;
    }}
    return total;
}}
'''
DIFF = '(M2C_FIELD(cursor, void **, 0) - 0x10) - cursor'


@pytest.mark.parametrize('maximum', (False, True))
def test_heap_spans_preserve_the_entry_register_and_distance_units(maximum):
    asm_update = ('subu $v1, $v0, $a0\nsltu $v0, $a1, $v1\nbnel $v0, $zero, .Lnext\naddu $a1, $v1, $zero'
                  if maximum else 'subu $v0, $v0, $a0\naddu $a1, $a1, $v0')
    source_update = f'value = {DIFF}; if (total < value) {{ total = value; }}' if maximum else f'total += {DIFF};'
    target = HEAP_TARGET.format(update=asm_update)
    source = HEAP_DRAFT.format(ctype='u32' if maximum else 's32', update=source_update,
                               extra='u32 value;' if maximum else '')
    [(family, candidate)] = draft_call_recovery.baseline_variants(source, 'span', target, '', 'gcc-2.7.2-kmc')
    assert family == heap_span_drafts.FAMILY
    assert 'span(u8 *start)' in candidate
    assert 'cursor = start;' in candidate
    assert 'M2C_FIELD(start, s32 *, 0) - (0x10 + (s32)start)' in candidate
    assert 'if (total < value)' in candidate if maximum else 'total += M2C_FIELD' in candidate
    assert not heap_span_drafts.rewrite(source, 'span', target.replace('lbu $v0, 8', 'lbu $v0, 9'))
    assert not heap_span_drafts.rewrite(source, 'span', target, 'int span(void *start);')


POLL_TARGET = '''
glabel f
lui $t6, %hi(status_word)
lw $a2, %lo(status_word)($t6)
addiu $sp, $sp, -8
andi $t7, $a2, 5
beqz $t7, .Ldone
nop
.Lpoll:
lui $t8, %hi(status_word)
lw $a2, %lo(status_word)($t8)
andi $t9, $a2, 5
bnez $t9, .Lpoll
nop
.Ldone:
lui $t0, (0x0 >> 16)
lw $t0, 0($t0)
lui $at, %hi(mapped)
or $v0, $zero, $zero
or $t1, $t0, $a0
or $t2, $t1, $at
lw $t3, %lo(mapped)($t2)
addiu $sp, $sp, 8
jr $ra
sw $t3, 0($a1)
endlabel f
'''
POLL_DRAFT = '''
extern M2C_UNK mapped;
extern s32 status_word;

s32 f(u32 addr, u32 *out) {
    if (status_word & 5) {
        do {
        } while (status_word & 5);
    }
    *out = *(*NULL | addr | (s32) &mapped);
    return 0;
}
'''


def test_mapped_poll_needs_both_resolved_addresses_and_an_actual_symbol_at_zero():
    symbols = {'status_word': 0xAF005004, 'mapped': 0xA0000000, 'D_00000000': 0}
    assert not ido_mapped_poll.rewrite(POLL_DRAFT, 'f', POLL_TARGET)
    [(family, candidate)] = draft_call_recovery.variants(
        POLL_DRAFT, 'f', POLL_TARGET, '', 'ido-7.1', resolve=symbols.get)
    assert family == ido_mapped_poll.FAMILY
    assert candidate.count('*(volatile u32 *)0xAF005004U') == 2
    assert 'extern u32 D_00000000;' in candidate
    assert '(D_00000000 | addr) | 0xA0000000U' in candidate
    assert 'extern s32 status_word' not in candidate
    assert not ido_mapped_poll.rewrite(POLL_DRAFT, 'f', POLL_TARGET.replace('bnez $t9, .Lpoll', 'bnez $t9, .Ldone'),
                                       resolve=symbols.get)
    symbols['D_00000000'] = 4
    assert not draft_call_recovery.variants(POLL_DRAFT, 'f', POLL_TARGET, '', 'ido-7.1', resolve=symbols.get)
