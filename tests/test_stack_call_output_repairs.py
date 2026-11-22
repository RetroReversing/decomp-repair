from decomprepair import stack_call_output_repairs as repair

SOURCE = """\
void f(void) {
    f32 buffer[3];
    f32 var_fp;
    sample(buffer, 1);
    note();
    sample(buffer, 2);
    var_fp = (0.0f - buffer[1]) - buffer[1];
    emit(var_fp);
}
"""

ASSEMBLY = (
    'jal sample',
    'addiu $a0, $sp, 0x20',
    'lwc1 $f0, 0x24($sp)',
    'mtc1 $fp, $f16',
    'sub.s $f16, $f16, $f0',
    'mfc1 $fp, $f16',
    'jal note',
    'nop',
    'jal sample',
    'addiu $a0, $sp, 0x20',
    'lwc1 $f2, 0x24($sp)',
    'mtc1 $fp, $f16',
    'sub.s $f16, $f16, $f2',
    'mfc1 $fp, $f16',
)


def propose(source, assembly=ASSEMBLY):
    return repair.variants(source, 'f', [('r', item, '') for item in assembly])


def test_recovers_each_overwritten_output_component_at_its_call():
    [(family, candidate)] = propose(SOURCE)
    assert family == repair.FAMILY
    assert 'sample(buffer, 1);\n    var_fp = 0.0f - buffer[1];\n    note();' in candidate
    assert 'sample(buffer, 2);\n    var_fp -= buffer[1];' in candidate


def test_requires_the_same_offset_and_accumulator_for_both_calls():
    for change in ('lwc1 $f2, 0x28($sp)', 'mtc1 $s7, $f16'):
        bad = (*ASSEMBLY[:10], change, *ASSEMBLY[11:]) if change.startswith('lwc1') else (
            *ASSEMBLY[:11], change, *ASSEMBLY[12:])
        assert not propose(SOURCE, bad)
    assert not propose(SOURCE, ASSEMBLY[:10])


def test_skips_when_early_destination_assignment_could_be_observed():
    assert not propose(SOURCE.replace('note();', 'note(var_fp);'))
    assert not propose(SOURCE.replace('    sample(buffer, 1);', '    share(&var_fp);\n    sample(buffer, 1);'))
    assert not propose(SOURCE.replace('note();', 'if (bad) return;'))
    assert not propose(SOURCE.replace('sample(buffer, 2);', 'if (ready) sample(buffer, 2);'))
    assert not propose(SOURCE.replace('var_fp', 'var_s7'))
