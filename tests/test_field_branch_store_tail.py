from decomprepair.branch_layout_repairs import store_tails

SOURCE = '''
#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void paint(void *obj, int selected) {
    if (selected) {
        M2C_FIELD(obj, u8 *, 0) = 0xFE;
    } else {
        M2C_FIELD(obj, u8 *, 0) = 0xFF;
    }
    M2C_FIELD(obj, u8 *, 3) = 0xFF;
}
'''


def test_duplicate_literal_field_store():
    [(family, candidate)] = store_tails(SOURCE, 'paint')
    assert family == 'branch_store_tail'
    assert candidate.count('M2C_FIELD(obj, u8 *, 3) = 0xFF;') == 2
    assert candidate.index('M2C_FIELD(obj, u8 *, 3)') < candidate.index('} else {')


def test_decline_hidden_effects_and_unsafe_control():
    for source, header in [
        (SOURCE.replace('(*(type_ptr)', '(effect(), *(type_ptr)'), ''),
        (SOURCE, '#undef M2C_FIELD'),
        (SOURCE, '#define obj other()'),
        (SOURCE.replace('M2C_FIELD(obj, u8 *, 3) = 0xFF;', 'M2C_FIELD(obj, u8 *, 3) = value();'), ''),
        (SOURCE.replace('if (selected) {', 'if (selected) {\n        const void *obj;'), ''),
        (SOURCE.replace('if (selected) {', 'if (selected) {\n        return;'), ''),
        (SOURCE.replace('    M2C_FIELD(obj, u8 *, 3)', '    /* keep comment */ M2C_FIELD(obj, u8 *, 3)'), ''),
    ]:
        assert store_tails(source, 'paint', header) == []
