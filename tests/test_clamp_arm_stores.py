from decomprepair.clamp_arm_stores import FAMILY, variants

COMMA = """
void clampit(s16 *a, f32 f) {
    s16 spA58[3];
    s32 temp_ft0;
    s32 var_v0;
    temp_ft0 = (s32) (f * 4096.0f);
    var_v0 = -0xDC;
    if (((s16) temp_ft0 < -0xDC) || (var_v0 = 0xDC, (((s16) temp_ft0 < 0xDD) == 0))) {
        spA58[1] = var_v0;
    }
    use(spA58);
}
"""

GOTO = """
void clampit(void) {
    s16 spA58[3];
    s32 var_v0_2;
    var_v0_2 = -0xDCU;
    if ((s16) spA58[2] >= -0xDC) {
        if ((s16) spA58[2] >= 0xDD) {
            var_v0_2 = 0xDC;
            goto block_42;
        }
    } else {
        { long long phantom_wide = arg1; }
block_42:
        spA58[2] = var_v0_2;
    }
    use(spA58);
}
"""


def test_comma_clamp_becomes_two_arm_stores():
    [(family, revised)] = variants(COMMA, 'clampit')
    assert family == FAMILY
    assert 'if ((s16) temp_ft0 < -0xDC) {\n        spA58[1] = -0xDC;\n    } else if (!((s16) temp_ft0 < 0xDD)) {\n        spA58[1] = 0xDC;\n    }' in revised
    assert 'var_v0 = ' not in revised.split('temp_ft0 = ')[1]
    assert variants(revised, 'clampit') == []


def test_goto_join_clamp_becomes_two_arm_stores():
    [(family, revised)] = variants(GOTO, 'clampit')
    assert family == FAMILY
    assert 'if ((s16) spA58[2] < -0xDC) {\n        spA58[2] = -0xDC;\n    } else if ((s16) spA58[2] >= 0xDD) {\n        spA58[2] = 0xDC;\n    }' in revised
    assert 'goto' not in revised and 'phantom_wide' not in revised


def test_both_shapes_are_offered_alone_and_together():
    both = COMMA.replace('    use(spA58);\n}', '    use(spA58);\n}\n', 1)
    combined = COMMA.replace('    use(spA58);', GOTO.split('{\n    s16 spA58[3];\n    s32 var_v0_2;\n')[1].rsplit('    use(spA58);', 1)[0] + '    use(spA58);')
    result = variants(combined, 'clampit')
    assert len(result) == 3 and all(f == FAMILY for f, _ in result)
    assert 'goto' not in result[-1][1] and '||' not in result[-1][1]
    assert both


def test_requires_the_second_bound_to_follow_the_first():
    assert variants(GOTO.replace('>= 0xDD', '>= 0xDE'), 'clampit') == []
    assert variants(COMMA.replace('var_v0 = 0xDC,', 'other = 0xDC,'), 'clampit') == []
    assert variants(COMMA.replace('var_v0 = -0xDC;', 'var_v0 = 0xDC;'), 'clampit') == []


FLOAT = """void steer(Obj *temp_s1)
{
    f32 temp_fv0_5;
    f32 var_fv1_2;
    temp_fv0_5 = temp_s1->x;
    var_fv1_2 = -0.5625f;
    if ((temp_fv0_5 < (-0.5625f)) || ((var_fv1_2 = 0.5625f, temp_fv0_5 > 0.5625f)))
    {
        temp_s1->x = var_fv1_2;
    }
    temp_s1->y = 1.0f;
}
"""


def test_float_comma_clamp_becomes_two_arm_stores():
    [(family, revised)] = variants(FLOAT, 'steer')
    assert family == FAMILY
    assert ('if (temp_fv0_5 < (-0.5625f)) {\n        temp_s1->x = -0.5625f;\n    } '
            'else if (temp_fv0_5 > 0.5625f) {\n        temp_s1->x = 0.5625f;\n    }') in revised
    assert 'var_fv1_2 =' not in revised
    assert variants(revised, 'steer') == []


def test_float_clamps_are_offered_together_too():
    two = FLOAT.replace('    temp_s1->y = 1.0f;\n', FLOAT.split('temp_s1->x;\n')[1].split('    temp_s1->y')[0]
                        .replace('temp_s1->x', 'temp_s1->z') + '    temp_s1->y = 1.0f;\n')
    result = variants(two, 'steer')
    assert len(result) == 3
    assert '||' not in result[-1][1]


def test_float_clamp_needs_its_own_temporary_in_both_places():
    assert variants(FLOAT.replace('var_fv1_2 = 0.5625f,', 'other = 0.5625f,'), 'steer') == []
