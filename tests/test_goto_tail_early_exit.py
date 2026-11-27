from decomprepair import goto_tail_early_exit, registry

DRAFT = """void update(Obj *arg0) {
    s16 temp_s1;

    temp_s1 = look(arg0);
    if (distance(arg0->x, arg0->y) < 0x2001U) {
        if (gShip->state == 0xFFFF) {
            goto block_3;
        }
        if (temp_s1 < 0x32) {
            gShip->vx += 1;
        }
        return;
    }
block_3:
    arg0->dead = 1;
}
"""

MERGED = """void update(Obj *arg0) {
    s16 temp_s1;

    temp_s1 = look(arg0);
    if (distance(arg0->x, arg0->y) >= 0x2001U || gShip->state == 0xFFFF) {
        arg0->dead = 1;
        return;
    }
    if (temp_s1 < 0x32) {
        gShip->vx += 1;
    }
}
"""

APART = """void update(Obj *arg0) {
    s16 temp_s1;

    temp_s1 = look(arg0);
    if (distance(arg0->x, arg0->y) >= 0x2001U) {
        arg0->dead = 1;
        return;
    }
    if (gShip->state == 0xFFFF) {
        arg0->dead = 1;
        return;
    }
    if (temp_s1 < 0x32) {
        gShip->vx += 1;
    }
}
"""


def test_exit_written_first():
    assert [s for _, s in goto_tail_early_exit.variants(DRAFT, 'update')] == [MERGED, APART]


def test_value_returns_and_two_guards():
    source = """s32 find(s32 a) {
    if (a > 0) {
        if (a == 3) goto none;
        if (a == 5) goto none;
        work(a);
        return 1;
    }
none:
    return 0;
}
"""
    merged = goto_tail_early_exit.variants(source, 'find')[0][1]
    assert 'if (a <= 0 || a == 3 || a == 5) {\n        return 0;\n    }\n    work(a);\n    return 1;\n}' in merged
    assert 'goto' not in merged


def test_declines():
    # a rest that falls into the label, a label used elsewhere, a tail with its own label, a value function that
    # falls off its end
    falls = DRAFT.replace('        return;\n    }\nblock_3', '    }\nblock_3')
    assert goto_tail_early_exit.variants(falls, 'update') == []
    reused = DRAFT.replace('    temp_s1 = look(arg0);\n', '    temp_s1 = look(arg0);\n    if (!arg0) goto block_3;\n')
    assert goto_tail_early_exit.variants(reused, 'update') == []
    labelled = DRAFT.replace('    arg0->dead = 1;\n', '    arg0->dead = 1;\nagain:\n    kill(arg0);\n')
    assert goto_tail_early_exit.variants(labelled, 'update') == []
    assert goto_tail_early_exit.variants(DRAFT.replace('void update', 's32 update'), 'update') == []


def test_registered():
    assert any(r.module == 'goto_tail_early_exit' for r in registry.declared())
