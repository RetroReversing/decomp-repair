from decomprepair.guard_temp_sink_repairs import FAMILY, variants

SOURCE = '''
void pop(void) {
    int next;
    do { next = count - 1; } while (0);
    if (count != 0) {
        count = next;
        top = marks[next];
    }
}
'''


def test_a_fenced_assignment_is_sunk_without_its_one_shot_loop():
    [(family, candidate)] = variants(SOURCE, 'pop')
    assert family == FAMILY
    assert 'if (count != 0) {\n        next = count - 1;\n' in candidate
    assert 'while (0)' not in candidate


def test_a_one_shot_loop_with_two_statements_is_left_alone():
    assert not variants(SOURCE.replace('next = count - 1;', 'next = count - 1; seen = 1;'), 'pop')
