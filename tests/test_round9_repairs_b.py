"""Round nine: a field read in a condition after the condition's store, and m2c's word store through a narrow
pointer."""
from decomprepair import field_load_hoist_repairs as h
from decomprepair import varargs_signature_repairs as v

HOIST = '''void f(void *arg0) {
    s16 temp_v0;
    void *temp_a2;

    temp_a2 = M2C_FIELD(arg0, void **, 0x6C);
    temp_v0 = M2C_FIELD(temp_a2, s16 *, 0x1C);
    if ((temp_v0 <= 0) || (M2C_FIELD(temp_a2, s16 *, 0x1C) = (s16) (temp_v0 - 1), (M2C_FIELD(arg0, f32 *, 0x28) < M2C_FIELD(M2C_FIELD(M2C_FIELD(arg0, void **, 0x20), void **, 0x3C), f32 *, 0x20)))) {
        M2C_FIELD(arg0, s32 *, 0x60) = (s32) (M2C_FIELD(arg0, s32 *, 0x60) | 1);
        return;
    }
    g(temp_a2);
}
'''


def test_a_field_read_after_the_conditions_store_is_hoisted():
    # An N64 function at 96.0%: the game read arg0->0x20 before the store; exact so.
    (family, out), = h.variants(HOIST, 'f')
    assert family == 'field_load_hoist'
    assert '    __repair_hoisted = M2C_FIELD(arg0, void **, 0x20);\n    if (' in out
    assert 'M2C_FIELD(M2C_FIELD(__repair_hoisted, void **, 0x3C), f32 *, 0x20)' in out


def test_a_condition_without_a_store_is_left_to_the_block_rule():
    plain = HOIST.replace('(M2C_FIELD(temp_a2, s16 *, 0x1C) = (s16) (temp_v0 - 1), ', '(')
    assert h.variants(plain, 'f') == []


WIDE = '''void f(void *p) {
    s8 *temp_a0;

    temp_a0 = M2C_FIELD(p, s8 **, 0x10);
    if (M2C_FIELD(p, u16 *, 0xC) & 0x800) {
        *temp_a0 = (s8) ((u32) M2C_FIELD(p, u32 *, 0x14) >> 8);
    } else {
        *temp_a0 = (s32) M2C_FIELD(p, u8 *, 0x16);
    }
}
'''


def test_m2cs_word_store_through_a_narrow_pointer():
    # An N64 function at 93.6%: one branch stored a byte, the other a word; exact with the word store spelled out.
    outs = [t for f, t in v.variants(WIDE, 'f', 'sb         $v0, 0x0($a0)\nsw         $v0, 0x0($a0)\n')
            if f == 'raw_store_width']
    assert any('        *(s32 *) temp_a0 = M2C_FIELD(p, u8 *, 0x16);' in t and '*temp_a0 = (s8)' in t for t in outs)
    assert not [t for f, t in v.variants(WIDE, 'f', 'sb         $v0, 0x0($a0)\n') if '*(s32 *) temp_a0' in t]
