from decomprepair import switch_default_tail_repairs as repair

SOURCE = """void f(int state, int other) {
    switch (state) {
        case 0:
            step();
        default:
        joined:
            record();
            switch (other) {
                case 2: step(); break;
                default: break;
            }
            break;
        case 1:
            goto joined;
        case 2:
            break;
    }
    finish();
}
"""


def test_lifts_shared_default_and_preserves_other_case_exits():
    [(family, candidate)] = repair.variants(SOURCE, 'f')
    assert family == repair.FAMILY
    assert candidate.index('default: goto joined;') < candidate.index('case 1:')
    assert candidate.index('case 2:\n            break;') < candidate.index('goto after_switch_tail;')
    assert candidate.index('goto after_switch_tail;') < candidate.index('joined:\n')
    assert candidate.index('joined:\n') < candidate.index('record();') < candidate.index('after_switch_tail: ;')
    assert 'case 2: step(); break;' in candidate
    assert candidate.count('record();') == 1
    assert repair.variants(candidate, 'f') == []


def test_skips_default_without_goto_from_later_cases():
    assert repair.variants(SOURCE.replace('goto joined;', 'break;'), 'f') == []


def test_skips_an_extra_break_owned_by_the_outer_switch():
    assert repair.variants(SOURCE.replace('record();', 'if (other) { break; }\n            record();'), 'f') == []


def test_skips_conditionally_executed_final_break():
    source = SOURCE.replace('            break;\n        case 1:', '            if (other) break;\n        case 1:')
    assert repair.variants(source, 'f') == []


def test_avoids_a_skip_label_already_in_use():
    source = SOURCE.replace('    finish();', '    after_switch_tail: finish();')
    [(_, candidate)] = repair.variants(source, 'f')
    assert 'goto after_switch_tail_;' in candidate
