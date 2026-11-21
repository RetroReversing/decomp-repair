

def test_likely_branch_sets_the_tested_bit_and_stores_to_the_original_field():
    from decomprepair.guard_inversion_repairs import rewrite_byte_toggle

    source = '''
void toggle(void *p) {
    u8 old;
    u8 next;
    old = M2C_FIELD(p, u8 *, 12);
    if (!(old & 4)) {
        next = old | 4;
    } else {
        next = old & 0xFB;
    }
    M2C_FIELD(p, u8 *, 12) = next;
}
'''
    asm = '''
lbu $v1, 12($a0)
andi $v0, $v1, 4
beql $v0, $zero, .Lmerge
ori $v0, $v1, 4
andi $v0, $v1, 0xfb
.Lmerge:
sb $v0, 12($a0)
'''
    patch = rewrite_byte_toggle(source, 'toggle', asm)
    assert patch
    assert 'if (old & 4) {\n        next = old & 0xFB;\n    } else {\n        next = old | 4;' in patch
    assert rewrite_byte_toggle(source, 'toggle', asm.replace('beql', 'bnel')) is None
    assert rewrite_byte_toggle(source, 'toggle', asm.replace('sb $v0, 12', 'sb $v0, 13')) is None
    assert rewrite_byte_toggle(source.replace('next = old | 4', 'next = old | 2'), 'toggle', asm) is None
