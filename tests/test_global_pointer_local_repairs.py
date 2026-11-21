

def test_scope_an_existing_global_pointer_local_for_a_measured_field_read():
    from decomprepair.global_pointer_local_repairs import scoped_field_reads

    source = """extern void *state;
void f(int enabled) {
    void *local;
    int field;
    field = (*(s32 *)((char *)(state) + 8));
    consume(field);
    local = state;
    consume(local);
}
"""
    rows = [
        (' ', 'lui $a1, %hi(state)', 'lui $v1, %hi(state)'),
        (' ', 'lw $a1, %lo(state)($a1)', 'lw $v1, %lo(state)($v1)'),
        ('<', 'addiu $a0, $zero, 4', ''),
        (' ', 'lw $v1, 8($a1)', 'lw $v1, 8($v1)'),
    ]
    [(family, candidate)] = scoped_field_reads(source, 'f', rows)
    assert family == 'measured_scoped_global_field'
    assert 'do {\n        local = state;\n    } while (0);\n    field' in candidate
    assert '((char *)(local) + 8)' in candidate
    assert not scoped_field_reads(source.replace('    field =', '    if (enabled)\n        field ='), 'f', rows)
    assert not scoped_field_reads(source.replace('consume(field);', 'consume(local);'), 'f', rows)
    assert not scoped_field_reads(source, 'f', rows[:2] + rows[-1:])
