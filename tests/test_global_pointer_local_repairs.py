

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


GUARDED = """extern void *gActor;
extern void f(void *);
void g(void *other, s32 *out, s32 mode) {
    gActor = NULL;
    if (mode) {
        gActor = other;
    }
    if ((gActor) != NULL) {
        switch (*(u16 *)((char *)gActor + 0x78)) {
        case 3:
            *out = 1;
            break;
        }
        *(s32 *)((char *)gActor + 0x60) |= mode;
        f(gActor);
    }
}
"""


def test_a_global_set_elsewhere_is_held_in_a_local_inside_its_tested_block():
    """A collision routine (KMC GCC 2.7.2) cleared the global at entry and stored it in a loop, and tested it at the
    end with a `switch` in the block: neither the `(G)` test, the `switch` nor the other stores may stop the child
    (15070 -> 13685 with the local, once its base-pointer scaffolding was gone)."""
    from decomprepair.global_pointer_local_repairs import variants

    [(family, text)] = variants(GUARDED, 'g')
    assert family == 'global_pointer_local'
    assert '__repair_gActor = gActor;\n    if ((__repair_gActor) != NULL) {' in text
    assert 'f(__repair_gActor);' in text and '((char *)__repair_gActor + 0x60)' in text
    # the stores before the block still name the global itself
    assert 'gActor = NULL;' in text and 'gActor = other;' in text


def test_a_store_to_the_global_inside_its_block_keeps_it_named():
    from decomprepair.global_pointer_local_repairs import variants

    assert not variants(GUARDED.replace('        f(gActor);\n', '        f(gActor);\n        gActor = NULL;\n'), 'g')
