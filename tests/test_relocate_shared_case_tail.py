from decomprepair import goto_structure_repairs as repair

SOURCE = """\
void f(int state, int first, int second) {
    float speed;
    switch (state) {
    case 3:
        if (first) {
            speed = 0.2f;
            goto shared;
        }
        if (second) {
            speed = 0.0f;
            if (other()) {
                goto done;
            }
        shared:
            begin(speed);
            finish();
        }
        goto done;
    }
done:
    report();
}
"""


def candidates(source):
    return [candidate for family, candidate in repair.variants(source, 'f')
            if family == repair.RELOCATE_FAMILY]


def test_moves_shared_tail_to_earlier_jump_and_keeps_common_continuation():
    [candidate] = candidates(SOURCE)
    assert candidate.index('shared:') < candidate.index('begin(speed);') < candidate.index('if (second)')
    assert candidate.index('begin(speed);') < candidate.index('goto done;') < candidate.index('if (second)')
    assert candidate.count('begin(speed);') == candidate.count('finish();') == 1
    assert candidate.index('if (second)') < candidate.index('goto shared;')
    assert candidate.count('shared:') == candidate.count('goto shared;') == 1


def test_skips_declarations_and_multiple_incoming_jumps():
    shadowed = SOURCE.replace('            speed = 0.0f;', '            float speed = 0.0f;')
    bypassed = SOURCE.replace('            speed = 0.2f;', '            float copy[first];\n            speed = 0.2f;')
    multiply_entered = SOURCE.replace('        if (second) {', '        if (second < 0) goto shared;\n        if (second) {')
    for source in (shadowed, bypassed, multiply_entered):
        assert not candidates(source)


def test_leaves_a_tail_with_another_continuation_in_place():
    assert not candidates(SOURCE.replace('        goto done;\n    }', '        update();\n        goto done;\n    }'))
    assert not candidates(SOURCE.replace('            finish();', '            return;'))



def test_keeps_unbraced_earlier_conditional_in_place():
    source = SOURCE.replace("if (first) {\n            speed = 0.2f;\n            goto shared;\n        }",
                            "if (first) goto shared;")
    assert not candidates(source)
