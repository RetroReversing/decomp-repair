from decomprepair import registry, shared_store_ladder

SOURCE = """void spawn(void *src, void *obj) {
    s32 temp;
    s32 var_v0_2;
    s8 var_v0;

    temp = M2C_FIELD(src, s32 *, 0x10);
    M2C_FIELD(obj, s32 *, 0x10) = temp;
    if (gMode == 0) {
        M2C_FIELD(obj, s32 *, 0x10) = (s32) (temp + 0x100);
        var_v0 = 5;
        goto block_9;
    }
    if (gMode != 1) {
        if (gMode == 2) {
            M2C_FIELD(obj, s32 *, 0x10) = (s32) (temp + 0x300);
            var_v0 = 7;
            goto block_9;
        }
    } else {
        M2C_FIELD(obj, s32 *, 0x10) = (s32) (temp + 0x200);
        var_v0 = 6;
block_9:
        M2C_FIELD(obj, s8 *, 0x20) = var_v0;
    }
    M2C_FIELD(obj, s32 *, 0x14) = temp;
    if (gMode == 0) {
        var_v0_2 = temp + 0x40;
        goto block_20;
    }
    if (gMode != 1) {
        if (gMode == 2) {
            var_v0_2 = M2C_FIELD(obj, s32 *, 0x14) + 0x60;
            goto block_20;
        }
    } else {
        var_v0_2 = M2C_FIELD(obj, s32 *, 0x14) + 0x50;
block_20:
        M2C_FIELD(obj, s32 *, 0x14) = var_v0_2;
    }
}
"""


def child(source):
    found = shared_store_ladder.variants(source, 'spawn')
    return found[0][1] if found else None


def test_every_ladder_becomes_compound_arms_in_one_child():
    text = child(SOURCE)
    assert text is not None and 'goto' not in text and 'var_v0' not in text and '!=' not in text
    for amount in ('0x100', '0x200', '0x300'):
        assert f'M2C_FIELD(obj, s32 *, 0x10) += {amount};' in text
    for amount in ('0x40', '0x50', '0x60'):
        assert f'M2C_FIELD(obj, s32 *, 0x14) += {amount};' in text
    assert 'M2C_FIELD(obj, s8 *, 0x20) = 6;' in text
    assert text.index('gMode == 1') < text.index('gMode == 2')


def test_no_compound_when_the_copy_changes_between():
    between = SOURCE.replace('M2C_FIELD(obj, s32 *, 0x10) = temp;\n',
                             'M2C_FIELD(obj, s32 *, 0x10) = temp;\n    temp = 0;\n')
    between = between.split('    M2C_FIELD(obj, s32 *, 0x14) = temp;')[0] + '}\n'
    assert child(between) is None


def test_no_compound_when_an_arm_calls():
    one = SOURCE.split('    M2C_FIELD(obj, s32 *, 0x14) = temp;')[0] + '}\n'
    assert child(one) is not None
    assert child(one.replace('var_v0 = 6;', 'notify();\n        var_v0 = 6;')) is None


def test_it_is_registered():
    assert shared_store_ladder.FAMILY in {f for repair in registry.declared() for f in repair.families}
