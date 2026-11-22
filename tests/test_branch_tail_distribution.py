

def test_measured_state_store_uses_each_arms_selected_constant():
    from decomprepair.branch_tail_distribution import measured_state_store_arms

    source = """void f(void *dst, void *object, int mode) {
    s16 next;
    if (mode == 3) {
        next = 1;
        *((s32 *) (((char *) object) + 0x10)) = 0;
    } else {
        *((s32 *) (((char *) object) + 0x10)) = lookup(mode);
        next = 7;
    }
    *((s16 *) (((char *) dst) + 0x7a)) = next;
}"""
    rows = [
        ('<', 'addiu $v0, $zero, 7', ''),
        ('r', 'sh $v0, 0x7a($s2)', 'sh $v1, 0x7a($s2)'),
    ]
    [(family, code)] = measured_state_store_arms(source, 'f', rows)
    assert family == 'branch_state_store'
    assert 'next =' not in code
    assert '+ 0x7a)) = 1;' in code
    assert '+ 0x7a)) = 7;' in code
    assert code.index('= lookup(mode);') < code.index('+ 0x7a)) = 7;')
    assert not measured_state_store_arms(source, 'f', rows[1:])
    assert not measured_state_store_arms(source.replace('lookup(mode)', 'lookup(next)'), 'f', rows)
    assert not measured_state_store_arms(source, 'f', rows, '#define lookup(x) call(x, next)')
