from decomprepair.measured_null_iteration_store import variants

SOURCE = """void f(int n) {
    int i;
    void *object;
    void *inner;
    i = 0;
    do {
        object = allocate(n);
        if (object != NULL) {
            inner = (*(void **)((char *)(object) + 8));
            (*(s16 *)((char *)(object) + 2)) = 0;
            (*(s16 *)((char *)(inner) + 0xC)) = (s16) (sample(4) + 4);
            (*(s16 *)((char *)(object) + 4)) = 8;
            consume(object);
        }
        i += 1;
    } while (i < n);
}
"""

ROWS = [('<', line, '') for line in (
    'move $s2, $v0', 'beql $s2, $zero, 0x30', 'addiu $s3, $s3, 1', 'lw $s1, 8($s2)',
    'addiu $a0, $zero, 4', 'addiu $v0, $zero, 8', 'sh $zero, 2($s2)', 'jal sample',
    'sh $v0, 4($s2)', 'addiu $v0, $v0, 4', 'sh $v0, 0xc($s1)',
)]


def test_null_iteration_and_measured_call_delay_slot():
    [(family, repaired)] = variants(SOURCE, 'f', ROWS)
    assert family == 'measured_null_iteration_store'
    assert 'if (!object) { i += 1; continue; }' in repaired
    assert 'do { i += 1; } while (0);' in repaired
    assert repaired.index(' + 4)) = 8;') < repaired.index('sample(4)')


def test_rejects_a_different_field_or_control_flow():
    assert not variants(SOURCE, 'f', ROWS[:-1])
    assert not variants(SOURCE.replace(' + 4)) = 8;', ' + 6)) = 8;'), 'f', ROWS)
    assert not variants(SOURCE.replace('consume(object);', 'if (n) continue;'), 'f', ROWS)
