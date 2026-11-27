from decomprepair import guard_ladder_early_exit, registry

DRAFT = """void update(Obj *arg0) {
    s32 temp;

    if (gActor != NULL) {
        if (gMode == 0) {
            if (gActor->state != 0xFFFF) {
                if ((gBusy == 0) && ((u32) gLevel >= 2U)) {
                    if (gActor->kind != 0xC8) {
                        goto block_6;
                    }
                    temp = arg0->timer - 1;
                    arg0->timer = temp;
                    return;
                }
                goto block_7;
            }
            goto block_6;
        }
        goto block_7;
    }
block_6:
block_7:
    gTimer = 0;
}
"""

MERGED = """void update(Obj *arg0) {
    s32 temp;

    if (gActor == NULL || gMode != 0 || gActor->state == 0xFFFF || gBusy != 0 || (u32) gLevel < 2U || gActor->kind != 0xC8) {
        gTimer = 0;
        return;
    }
    temp = arg0->timer - 1;
    arg0->timer = temp;
}
"""


def test_ladder_flattened_to_one_early_exit():
    children = [source for _, source in guard_ladder_early_exit.variants(DRAFT, 'update')]
    assert children[0] == MERGED
    assert len(children) == 2
    assert children[1].count('gTimer = 0;') == 6
    assert 'goto' not in children[1]


def test_other_jumps_into_the_labels_decline():
    other = DRAFT.replace('                    arg0->timer = temp;\n',
                          '                    arg0->timer = temp;\n                    if (temp) { goto block_6; }\n')
    assert guard_ladder_early_exit.variants(other, 'update') == []


def test_a_single_level_is_left_to_goto_tail_early_exit():
    source = """void f(s32 a) {
    if (a > 0) {
        if (a == 3) {
            goto out;
        }
        g(a);
        return;
    }
out:
    g(0);
}
"""
    assert guard_ladder_early_exit.variants(source, 'f') == []


def test_labels_with_a_jump_after_the_work_decline():
    source = DRAFT.replace('    gTimer = 0;\n', '    gTimer = 0;\nlast:\n    gTimer = 1;\n')
    assert guard_ladder_early_exit.variants(source, 'update') == []


def test_declared():
    families = [family for repair in registry.declared() for family in repair.families]
    assert {'guard_ladder_early_exit', 'guard_ladder_prefix_exit'} <= set(families)


PREFIXED = """void update(Obj *arg0) {
    s32 level;

    if (gTarget != NULL) {
        if (M2C_FIELD(gTarget, u16 *, 0x6A) == 0xFFFF) {
            arg0->timer = 0xFFFF;
            return;
        }
        level = 0x80 - distance(gTarget);
        arg0->level = level;
        if (level > 0) {
            if (M2C_FIELD(gTarget, u16 *, 0x6A) != 0xFFFF) {
                if (gTarget == NULL) {
                    goto block_7;
                }
                arg0->timer = 9;
                return;
            }
            goto block_8;
        }
        goto block_7;
    }
block_7:
block_8:
    arg0->timer = 0xFFFF;
}
"""

PREFIX_MERGED = """void update(Obj *arg0) {
    s32 level;

    if (gTarget == NULL) {
        goto block_7;
    }
    if (M2C_FIELD(gTarget, u16 *, 0x6A) == 0xFFFF) {
        arg0->timer = 0xFFFF;
        return;
    }
    level = 0x80 - distance(gTarget);
    arg0->level = level;
    if (level <= 0 || M2C_FIELD(gTarget, u16 *, 0x6A) == 0xFFFF || gTarget == NULL) {
block_7:
block_8:
        arg0->timer = 0xFFFF;
        return;
    }
    arg0->timer = 9;
}
"""


def test_a_ladder_after_other_work_takes_the_labels_into_its_exit():
    assert guard_ladder_early_exit.variants(PREFIXED, 'update') == [('guard_ladder_prefix_exit', PREFIX_MERGED)]


def test_a_prefix_that_jumps_to_the_labels_declines():
    source = PREFIXED.replace('        arg0->level = level;\n',
                              '        if (level == 1) { goto block_8; }\n        arg0->level = level;\n')
    assert guard_ladder_early_exit.variants(source, 'update') == []
