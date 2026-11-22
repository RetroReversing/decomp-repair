from decomprepair.measured_kmc_second_call_argument import variants

SOURCE = '''s32 helper();
void f(void *arg) {
    s32 value;
    value = (u16)helper(arg);
}'''
ROWS = [(' ', 'nop', 'nop')] * 20 + [
    ('o', '', 'jal helper'),
    (' ', 'move $a0, $s0', 'move $a0, $s0'),
    ('o', 'jal helper', ''),
    ('<', 'addiu $a1, $zero, 3', '')]


def test_supplies_observed_second_argument():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_constant_second_call_argument'
    assert 'helper(arg, 3)' in fixed


def test_requires_unprototyped_unique_call_and_target_evidence():
    assert not variants(SOURCE.replace('helper();', 'helper(void *, s32);'), 'f', '', ROWS)
    assert not variants(SOURCE, 'f', 's32 helper(void *);', ROWS)
    assert not variants(SOURCE.replace('helper(arg);', 'helper(arg); helper(arg);'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('helper(arg)', 'helper(arg + 1)'), 'f', '', ROWS)
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
