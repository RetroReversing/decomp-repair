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


from decomprepair import global_record_copy_repairs as g  # noqa: E402

COPY = '''void *f(void *arg0) {
    D_8011F108 = (s32) ((__repair_record_arg0*)arg0)->field_0;
    D_8011F10C = (s32) ((__repair_record_arg0*)arg0)->field_4;
    D_8011F110 = (s32) ((__repair_record_arg0*)arg0)->field_8;
    return arg0;
}
'''
ASM = 'addiu      $a2, $a2, %lo(D_8011F108)\nsw         $v1, 0x0($a2)\n'


def test_consecutive_globals_from_consecutive_fields_are_one_record_copy():
    # An N64 function at 90.3%: exact as one 12-byte copy.
    (family, out), = g.variants(COPY, 'f', ASM)
    assert family == 'global_record_copy'
    assert 'typedef struct { s32 w[3]; } __repair_record_copy_3;' in out
    assert '    *(__repair_record_copy_3 *) &D_8011F108 = *(__repair_record_copy_3 *) arg0;\n    return arg0;' in out


def test_left_alone_otherwise():
    assert g.variants(COPY, 'f', 'lui        $at, %hi(D_8011F108)\n') == []  # each global addressed on its own
    assert g.variants(COPY.replace('field_8', 'field_C'), 'f', ASM)[0][1].count('w[2]') == 1  # offsets break the run
    assert g.variants(COPY.replace('D_8011F10C', 'D_8011F200'), 'f', ASM) == []  # not consecutive addresses
