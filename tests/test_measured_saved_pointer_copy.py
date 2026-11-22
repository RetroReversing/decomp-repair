from decomprepair.measured_saved_pointer_copy import variants

SOURCE = '''s32 release(void *);
s32 dispose(void *object) {
    void *child;
    if (object != NULL) {
        child = M2C_FIELD(object, void **, 16);
        if (child != NULL) { release(child); M2C_FIELD(object, void **, 16) = NULL; }
        return release(object);
    }
    return 0;
}'''
T = ['move $s0, $a0', 'sw $s1, 20($sp)', 'move $s1, $s0', 'jal release', 'move $a0, $s1']
C = ['move $s0, $a0', 'sw $ra, 20($sp)', 'nop', 'jal release', 'move $a0, $s0']
ROWS = [('r', a, b) for a, b in zip(T, C)]


def test_keeps_pointer_in_separate_final_call_lifetime():
    label, fixed = variants(SOURCE, 'dispose', '', ROWS)[0]
    assert label == 'measured_saved_pointer_copy'
    assert 'void *__repair_saved_pointer = object;' in fixed
    assert 'return release(__repair_saved_pointer);' in fixed
    assert 'M2C_FIELD(object, void **, 16)' in fixed


def test_requires_evidence_and_an_unmodified_unescaped_parameter():
    assert not variants(SOURCE, 'dispose', '', [(' ', a, a) for a in T])
    assert not variants(SOURCE.replace('child = M2C_FIELD', 'object = child; child = M2C_FIELD'), 'dispose', '', ROWS)
    assert not variants(SOURCE.replace('child = M2C_FIELD', 'escape(&object); child = M2C_FIELD'), 'dispose', '', ROWS)
    assert not variants(SOURCE, 'dispose', '#define object other', ROWS)
    assert not variants(SOURCE.replace('void *object)', 'volatile void *object)'), 'dispose', '', ROWS)
