from decomprepair.do_exit_into_loop import variants
from decomprepair.statement_slide import variants as slides

SOURCE = """s32 f(u16 index, u16 start) {
    start = index;
    do {
        index = next[index];
    } while (index != start);
    log_message(text);
    index = start;
done:
    return index;
}
"""


def test_the_tail_moves_into_the_loop_on_the_negated_test():
    [(family, child)] = variants(SOURCE, 'f')
    assert family == 'do_exit_into_loop'
    assert 'for (;;) {' in child and 'if (index == start) {\nlog_message(text);\n    index = start;\nbreak;' in child
    assert child.index('break;') < child.index('done:')


def test_a_break_or_continue_or_a_tail_without_a_call_is_left_alone():
    assert not variants(SOURCE.replace('index = next[index];', 'if (x) break;'), 'f')
    assert not variants(SOURCE.replace('index = next[index];', 'if (x) continue;'), 'f')
    assert not variants(SOURCE.replace('log_message(text);', 'flag = 1;'), 'f')


def test_a_parameter_store_slides_above_the_call():
    source = SOURCE.replace('done:\n', '    flag = 0;\n')
    assert any("index = start;\n    log_message(text);" in child for _, child in slides(source, "f"))
