from decomprepair.guarded_compare_switch import variants

SOURCE = '''
typedef int s32;
void f(s32 v, s32 input) {
    s32 copy;
    if (v != 16) {
        if (v < 17) {
            if (v != 7) {
                s32 local;
                local = input & 255;
                if (v != 10) { return; }
                use(local);
            } else { use(7); }
        } else if (v == 64) { use(64); }
        else {
            copy = input & 255;
            if (v != 91) { return; }
            use(copy);
        }
    } else { use(16); }
}
'''


def test_rebuilds_guarded_dispatch_and_keeps_computations():
    results = [text for _, text in variants(SOURCE, 'f')]
    assert results
    full = [text for text in results if all(f'case {value}:' in text for value in ('0xa', '0x7', '0x10', '0x40', '0x5b'))]
    assert full
    assert 'local = input & 255;' in full[0]
    assert 'copy = input & 255;' in full[0]
    assert 'default:\n' in full[0] and 'return;' in full[0]
    assert any(text.index('case 0x10:') < text.index('case 0x40:') for text in full)


def test_does_not_discard_observable_prefix():
    for changed in (SOURCE.replace('s32 copy;', 'static s32 copy;'),
                    SOURCE.replace('s32 input)', 'volatile s32 input)'),
                    SOURCE.replace('copy = input & 255;', 'global = input & 255;'),
                    SOURCE.replace('copy = input & 255;', 'copy = read() & 255;')):
        assert not any('case 0x5b:' in text for _, text in variants(changed, 'f'))


def test_does_not_turn_ranges_into_cases():
    changed = SOURCE.replace('if (v != 91) { return; }', 'if (v < 91) { return; }')
    assert not any('case 0x5b:' in text for _, text in variants(changed, 'f'))
