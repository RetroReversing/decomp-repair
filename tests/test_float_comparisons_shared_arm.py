from decomprepair import float_comparisons_shared_arm as repair

ASM = '''c.eq.s $f2, $f0
nop
bc1t .Lspecial
nop
c.eq.s $f2, $f0
nop
nop
bc1t .Lspecial
nop
'''
SOURCE = '''void f(void) {
    f32 value;
    if ((value != 1.0f) && (value != -1.0f)) {
        normal();
    } else {
        special();
    }
    after();
}
'''


def test_direct_equality_branches_keep_both_arm_scopes():
    out = repair.variants(SOURCE, 'f', ASM)
    assert len(out) == 1
    text = out[0][1]
    assert 'if (value == 1.0f) goto branch_else_0;' in text
    assert 'if (value == -1.0f) goto branch_else_0;' in text
    assert text.index('normal();') < text.index('branch_else_0:') < text.index('special();')
    assert 'branch_done_0:;' in text and 'after();' in text


def test_float_comparisons_agree_including_nan():
    for value in (-2.0, -1.0, -0.0, 0.0, 1.0, 2.0, float('nan')):
        assert ((value != 1.0) and (value != -1.0)) == (not (value == 1.0 or value == -1.0))


def test_requires_evidence_plain_float_and_private_control_flow():
    assert repair.variants(SOURCE, 'f', ASM.replace('.Lspecial', '.Lother', 1)) == []
    assert repair.variants(SOURCE.replace('f32 value;', 'volatile f32 value;'), 'f', ASM) == []
    assert repair.variants(SOURCE.replace('normal();', 'goto other;'), 'f', ASM) == []
    assert repair.variants(SOURCE.replace('normal();', 'return;'), 'f', ASM) == []
    assert repair.variants(SOURCE, 'f', ASM, '#define value side_effect()') == []
    assert repair.variants(SOURCE, 'f', ASM, 'typedef volatile float f32;') == []


def test_generated_labels_do_not_collide_with_header_macros():
    out = repair.variants(SOURCE, 'f', ASM, '#define branch_else_0 existing')
    assert out and 'goto branch_else_1;' in out[0][1]


def test_branch_likely_also_proves_shared_target():
    assert repair.evidence(ASM.replace('bc1t ', 'bc1tl '))
