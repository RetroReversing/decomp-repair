from decomprepair import conversion_scheduling_repairs

SOURCE = '''
int choose(unsigned char arg) {
    unsigned char flag;
    flag = arg;
    if (((signed char) flag) == 0) {
        report();
    }
    if (((signed char) flag) != 0) {
        return 2;
    }
    return (signed char) flag;
}
'''
ASSEMBLY = 'sll $v0, $t0, 24\nsra $v1, $v0, 24\nbnez $v1, other'


def test_rewrites_both_zero_tests_without_changing_other_casts():
    [(family, candidate)] = conversion_scheduling_repairs.narrow_zero_tests(
        SOURCE, 'choose', arch='mips', asm=ASSEMBLY,
    )
    assert family == 'narrow_zero_test_shift'
    assert candidate.count('((unsigned int)flag << 24)') == 2
    assert 'return (signed char) flag;' in candidate


def test_requires_matching_width_register_and_polarities():
    rewrite = conversion_scheduling_repairs.narrow_zero_tests
    for arch, source, asm in (
        ('arm', SOURCE, ASSEMBLY),
        ('mips', SOURCE, ASSEMBLY.replace('24', '16')),
        ('mips', SOURCE, ASSEMBLY.replace('$v1, $v0', '$v1, $v1')),
        ('mips', SOURCE.replace('!= 0', '== 0'), ASSEMBLY),
    ):
        assert rewrite(source, 'choose', arch=arch, asm=asm) == []
