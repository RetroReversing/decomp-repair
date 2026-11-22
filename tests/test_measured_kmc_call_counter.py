from decomprepair.measured_kmc_call_counter import variants

SOURCE = '''void f(void) {
    s32 counter;
    if (!(flags & 2)) {
        counter = 0;
        if (check((char *)&state + 0x20) != 0) {
            do {
                run(counter);
                counter += 1;
            } while (counter == 0);
        }
    }
}'''
ROWS = [(' ', 'nop', 'nop')] * 22 + [
    (' ', 'jal check', 'jal check'),
    ('o', 'addiu $a0, $a0, %lo(target)', 'move $s1, $zero'),
    (' ', 'beqz $v0, 84', 'beqz $v0, 88'),
    ('o', 'move $s1, $zero', 'nop')]


def test_moves_counter_initialization_into_success_branch():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_call_then_counter_init'
    assert fixed.index('if (check(') < fixed.index('counter = 0;') < fixed.index('run(counter)')


def test_requires_no_later_or_escaped_counter_and_matching_evidence():
    assert not variants(SOURCE.replace('run(counter);', 'run(&counter);'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('    }\n}', '    }\n    run(counter);\n}'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('s32 counter;', 'volatile s32 counter;'), 'f', '', ROWS)
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('check(', 'other('), 'f', '', ROWS)
