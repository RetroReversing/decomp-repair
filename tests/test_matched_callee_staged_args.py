from decomprepair.matched_callee_staged_args import variants

SOURCE = '''s16 volume_fn(void *, void *);
void set_volume(void *, s16, s32);
void f(void *voice, void *player) {
    set_volume((u8 *) voice + 4, volume_fn(voice, player), duration_fn(voice, M2C_FIELD(player, s32 *, 0x1C)));
}
'''
CALLEE = 's32 volume_fn(void *v, void *p) { return 1; }'
ASM = '''jal old_volume_address
nop
jal duration_fn
addu $s0, $v0, $zero
addiu $a0, $s1, 4
sll $a1, $s0, 16
sra $a1, $a1, 16
jal set_volume_address
'''


def test_stages_calls_with_matched_return_width():
    out = variants(SOURCE, 'f', ASM, CALLEE)
    assert len(out) == 1
    assert 's32 volume_fn(void *, void *);' in out[0][1]
    assert 's32 volume = volume_fn(voice, player);' in out[0][1]
    assert 'set_volume((u8 *) voice + 4, volume, duration);' in out[0][1]


def test_requires_matched_return_and_target_sequence():
    assert not variants(SOURCE, 'f', ASM, '')
    assert not variants(SOURCE, 'f', ASM, CALLEE.replace('s32', 's16'))
    assert not variants(SOURCE, 'f', ASM.replace('sll $a1, $s0, 16', 'nop'), CALLEE)
    assert not variants(SOURCE, 'f', ASM, CALLEE, '#define s32 volatile int')
