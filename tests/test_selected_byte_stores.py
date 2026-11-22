from decomprepair.branch_layout_repairs import scalar_tails

SOURCE = '''
extern unsigned char selected;
extern unsigned char fallback;
extern volatile int observed;
void f(int outer, int inner) {
    volatile short temp;
    if (outer != 0) {
        if (1) {
            if (inner) { temp = 4; } else { temp = 4; }
        }
        if (observed == 0) {}
    } else if (1) { temp = fallback; }
    selected = temp;
}
'''


def test_distributes_a_selected_byte_into_its_arms():
    [(family, result)] = scalar_tails(SOURCE, 'f')
    assert family == 'branch_store_tail'
    assert 'volatile short temp;' not in result
    assert result.count('if (observed == 0) {} selected = 4;') == 2
    assert 'else { selected = fallback; }' in result


def test_preserves_scratch_with_additional_uses_and_rejects_wider_sources():
    assert not scalar_tails(SOURCE.replace('selected = temp;', 'selected = temp; consume(&temp);'), 'f')
    assert not scalar_tails(SOURCE.replace('unsigned char fallback', 'int fallback'), 'f')
    assert not scalar_tails(SOURCE.replace('temp = 4;', 'temp = 256;'), 'f')
