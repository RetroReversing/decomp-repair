from decomprepair.target_switch_upper_guard import variants

SOURCE = '''void f(int input) {
    int x;
    x = input;
    switch (x) {
    case 7: one(); break;
    case 10: two(); break;
    case 16: three(); break;
    }
}
'''
ASM = 'slti $v0, $v1, 0x14\nbeqz $v0, 0x100\n'


def test_target_bound_offers_guard():
    children = variants(SOURCE, 'f', ASM)
    assert len(children) == 1
    assert 'if (x < 0x14) switch (x)' in children[0][1]


def test_no_evidence_or_case_outside_range():
    assert not variants(SOURCE, 'f', '')
    assert not variants(SOURCE.replace('case 16:', 'case 20:'), 'f', ASM)
    assert not variants(SOURCE.replace('case 16:', 'default:'), 'f', ASM)


def test_dangling_else_and_goto_are_rejected():
    assert not variants(SOURCE.replace('    switch', '    if (x) switch').replace('    }\n}', '    } else two();\n}'), 'f', ASM)
    assert not variants(SOURCE.replace('    switch', '    goto out;\n    switch'), 'f', ASM)


def test_macro_or_volatile_type_is_rejected():
    assert not variants(SOURCE, 'f', ASM, '#define x read()')
    assert not variants(SOURCE.replace('int x;', 's32 x;'), 'f', ASM, 'typedef volatile int s32;')
