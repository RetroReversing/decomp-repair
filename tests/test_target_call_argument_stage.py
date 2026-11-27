from decomprepair.target_call_argument_stage import variants

SOURCE = '''void f(void *voice, void *player) {
    s32 delta;
    s32 pan;
    delta = osc();
    consume(delta);
    pan = get_pan(voice, player);
    start(voice, player, 1, get_vol(voice, player), pan & 0xFF, 0, M2C_FIELD(player, s32 *, 0));
}
'''
ASM = '''sw $a2, 0x18($sp)
sll $v0, $v0, 16
jal start
sra $a3, $v0, 16
'''


def test_stages_both_arguments_into_dead_carrier():
    children = variants(SOURCE, 'f', ASM)
    assert len(children) == 1
    assert 's16 note_vol;' in children[0][1]
    assert 'note_vol = get_vol(voice, player); delta = M2C_FIELD(player, s32 *, 0);' in children[0][1]


def test_rejects_missing_evidence_live_carrier_or_loop():
    assert not variants(SOURCE, 'f', '')
    assert not variants(SOURCE.replace('start(voice, player, 1,', 'start(voice, player, delta,'), 'f', ASM)
    assert not variants(SOURCE.replace('}\n', '    consume(delta);\n}\n'), 'f', ASM)
    assert not variants(SOURCE.replace('    pan =', '    while (0) {}\n    pan ='), 'f', ASM)
    assert not variants(SOURCE, 'f', ASM, '#define note_vol x')
