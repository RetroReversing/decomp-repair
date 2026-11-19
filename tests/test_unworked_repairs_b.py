"""Round-seven repairs: global pointer byte steps, symbols read through a just-set pointer, a leaf's unused frame,
unsigned narrow locals, and masks on word parameters."""
from decomprepair import leaf_frame_repairs as leaf
from decomprepair import parameter_mask_drop_repairs as masks
from decomprepair import pointer_scale_repairs as scale
from decomprepair import stored_pointer_read_repairs as stored

WALK = '''extern u16 D_800BF680;
extern u16 *D_80102F40;

s32 f(s32 arg0) {
    s32 var_a2;
    u16 temp_v1;

    D_80102F40 = &D_800BF680;
    var_a2 = 0;
    if (D_800BF680 != 0) {
loop_1:
        if (M2C_FIELD(D_80102F40, u8 *, 5) != arg0) {
            temp_v1 = M2C_FIELD(D_80102F40, u16 *, 0xC);
            D_80102F40 += 0xC;
            var_a2 += 1;
            if (temp_v1 != 0) {
                goto loop_1;
            }
        }
    }
    return var_a2;
}
'''
WALK_ASM = 'addiu      $v0, $v0, %lo(D_800BF680)\nlhu        $v1, 0xc($a1)\naddiu      $v0, $a1, 0xc\n'


def test_a_global_pointer_steps_in_elements():
    # An N64 list walk stepped 0xC bytes on a `u16 *` global; the draft's `+= 0xC` stepped 0x18.
    (family, out), = scale.variants(WALK, 'f', WALK_ASM)
    assert family == 'pointer_byte_step' and 'D_80102F40 += 6;' in out


def test_the_symbol_is_read_through_the_pointer_just_set():
    (family, out), = stored.variants(WALK, 'f')
    assert family == 'stored_pointer_read'
    assert 'if (*D_80102F40 != 0) {' in out and 'D_80102F40 = &D_800BF680;' in out
    # not past a call, which may change either
    assert stored.variants(WALK.replace('    var_a2 = 0;\n', '    g();\n    var_a2 = 0;\n'), 'f') == []


LEAF = '''s32 f(void *arg0, u32 arg2) {
    s32 var_t0;
    s8 temp_a1;
    s8 temp_v0;

    var_t0 = 0;
    temp_v0 = 1 << M2C_FIELD(arg0, s32 *, 4);
    temp_a1 = 1 << arg2;
    if (*(u8 *)arg0 & temp_v0) {
        var_t0 |= temp_a1 & 0xFF;
    }
    return var_t0;
}
'''
LEAF_ASM = 'addiu      $sp, $sp, -8\nlbu        $v1, ($a3)\nand        $v1, $v1, $v0\njr         $ra\naddiu      $sp, $sp, 8\n'


def test_a_leafs_unused_frame_and_unsigned_narrow_locals():
    # An N64 leaf opened an 8-byte frame it never stored to, and masked a byte with an unsigned `1 << n`.
    out = leaf.variants(LEAF, 'f', LEAF_ASM)
    frames = [t for f, t in out if f == 'unused_frame_local']
    assert frames and 'u8 __repair_frame[8];' in frames[0]
    unsigned = [t for f, t in out if f == 'unsigned_narrow_local']
    assert any('    u8 temp_v0;' in t and '    s8 temp_a1;' in t for t in unsigned)
    assert any('    u8 temp_v0;' in t and '    u8 temp_a1;' in t for t in unsigned)


def test_left_alone_where_the_target_saves_calls_or_sign_extends():
    assert not [f for f, _ in leaf.variants(LEAF, 'f', LEAF_ASM + 'sw         $ra, 0x14($sp)\n') if f == 'unused_frame_local']
    assert not [f for f, _ in leaf.variants(LEAF, 'f', LEAF_ASM + 'jal        g\n') if f == 'unused_frame_local']
    assert not [f for f, _ in leaf.variants(LEAF, 'f', LEAF_ASM + 'sra        $v0, $v0, 0x18\n') if f == 'unsigned_narrow_local']


MASKED = '''void f(void *arg0, s32 arg1, u16 arg5) {
    g(arg0, arg5);
    g((arg1 & 0xFFFF), arg5);
    if ((arg1 & 0xFFFF) != 0) {
        h((arg1 & 0xFFFF));
    }
}
'''


def test_masks_the_target_never_applies_are_dropped():
    # An N64 function passed and tested the word itself: 97.3% with three masks, exact without them.
    (family, out), = masks.variants(MASKED, 'f', 'move       $s1, $a1\nlhu        $s0, 0x46($sp)\n')
    assert family == 'parameter_mask_drop'
    assert '& 0xFFFF' not in out and 'g(arg1, arg5);' in out and 'if (arg1 != 0) {' in out
    assert masks.variants(MASKED, 'f', 'andi $a0, $s1, 0xffff\n' * 3) == []
