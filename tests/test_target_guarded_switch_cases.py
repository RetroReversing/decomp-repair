from decomprepair.target_guarded_switch_cases import variants

SOURCE = '''void f(int input) {
    int x;
    x = input;
    if (x < 0x1C) {
        if (x < 0x14) switch (x) {
        case 7: one(); break;
        case 10: two(); break;
        case 16: three(); break;
        }
    } else if (x != 0x5B) {
        if (x == 0x40) { four(); }
    } else { five(); }
}
'''
ASM = '''slti $v0, $v1, 0x1c
slti $v0, $v1, 0x14
slti $v0, $v1, 0x5c
'''


def test_reconstructs_switch_and_noop_cases():
    children = variants(SOURCE, 'f', ASM)
    assert len(children) == 2
    assert all('switch (x)' in text and 'case 20:' in text and 'case 27:' in text for _, text in children)
    assert 'case 93:' in children[1][1]
    assert 'case 0x40:' in children[1][1] and 'case 0x5B:' in children[1][1]


def test_requires_target_and_rejects_control_transfer():
    assert not variants(SOURCE, 'f', '')
    assert not variants(SOURCE, 'f', ASM.replace('0x5c', '0x5d'))
    assert not variants(SOURCE.replace('four();', 'break;'), 'f', ASM)
    assert not variants(SOURCE.replace('case 16:', 'case 17:'), 'f', ASM)


def test_rejects_macro_selector_or_volatile_typedef():
    assert not variants(SOURCE, 'f', ASM, '#define x poll()')
    assert not variants(SOURCE.replace('int x;', 's32 x;'), 'f', ASM, 'typedef volatile int s32;')
