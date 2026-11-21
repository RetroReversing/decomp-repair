"""counter_stride_inline, call_window_global_local and staged_float_constant (a record-initialising loop)."""
from decomprepair import record_init_shapes as shapes

SOURCE = """s32 clear_ids();
void *alloc();
extern void *gRecords;
extern u8 gMask;

s32 init_records(void) {
    s32 count;
    s32 off;
    void *a;
    void *b;
    void *c;

    gRecords = alloc(1);
    count = 0;
    off = 0;
    do {
        a = gRecords + off;
        (*(s16 *)((char *)(a) + 0x80)) = 1;
        (*(f32 *)((char *)(a) + 0x74)) = 255.0f;
        (*(f32 *)((char *)(a) + 0x38)) = 999.0f;
        (*(u8 *)((char *)(a) + 0x99)) = 0xFF;
        b = gRecords + off;
        (*(u8 *)((char *)(b) + 0x98)) = 0xFF;
        count += 1;
        off += 0xD4;
        (*(s16 *)((char *)(b) + 0x96)) = 0;
    } while (count < 0x38);
    clear_ids(off);
    gMask = 4;
    (*(s32 *)((char *)(gRecords) + 0x2B30)) = 0;
    (*(s32 *)((char *)(gRecords) + 0x2B3C)) = 0;
    alloc(gRecords);
    return 1;
}
"""
ASM = "addiu $a0, $a0, 0xD4\n"


def test_offset_variable_becomes_counter_times_stride():
    [(family, child)] = shapes.counter_stride_inline(SOURCE, 'init_records', 'mips', ASM)
    assert family == 'counter_stride_inline'
    assert 'a = gRecords + (count * 0xD4);' in child
    assert 'off += 0xD4' not in child and 'off = 0;' not in child and 's32 off;' not in child
    assert 'clear_ids();' in child  # the dead offset argument goes with the variable


def test_counter_stride_needs_the_targets_stride_register():
    assert not shapes.counter_stride_inline(SOURCE, 'init_records', 'mips', 'addiu $a0, $a0, 0x10\n')
    assert not shapes.counter_stride_inline(SOURCE, 'init_records', 'ppc', ASM)


def test_counter_stride_keeps_a_use_of_the_offset_it_cannot_replace():
    source = SOURCE.replace('clear_ids(off);', 'clear_ids(off + 1);')
    assert not shapes.counter_stride_inline(source, 'init_records', 'mips', ASM)
    late = SOURCE.replace('off += 0xD4;', 'off += 0xD4;\n        b = gRecords + off;')
    assert not shapes.counter_stride_inline(late, 'init_records', 'mips', ASM)


def test_global_pointer_held_from_the_previous_call():
    children = shapes.call_window_global_local(SOURCE, 'init_records')
    assert children and children[0][0] == 'call_window_global_local'
    child = children[0][1]
    assert child.index('__repair_gptr0 = gRecords;') < child.index('gMask = 4;')
    assert '(__repair_gptr0) + 0x2B30' in child and 'alloc(__repair_gptr0)' in child
    assert 'void *__repair_gptr0;' in child


def test_global_pointer_local_leaves_a_window_that_assigns_it():
    source = SOURCE.replace('gMask = 4;', 'gRecords = 0;')
    assert not any('(__repair_gptr0) + 0x2B30' in child for _, child in shapes.call_window_global_local(source, 'init_records'))


def test_float_constant_staged_where_it_stood_and_stored_after_the_next_temporary():
    children = [child for _, child in shapes.staged_float_constant(SOURCE, 'init_records')]
    both = [c for c in children if '__repair_fconst1 = 999.0f;' in c and '0x38)) = __repair_fconst1;' in c
            and c.index('0x38)) = __repair_fconst1;') > c.index('b = gRecords')]
    assert len(both) == 1
    child = both[0]
    assert child.index('__repair_fconst1 = 999.0f;') < child.index('b = gRecords') < child.index('= __repair_fconst1;')
    assert 'f32 __repair_fconst1;' in child
    assert any('= 999.0f;' in c and '__repair_fconst1' not in c for c in children)  # the sunk-only form


def test_float_zero_is_not_staged():
    source = SOURCE.replace('255.0f', '0.0f').replace('999.0f', '0.0f')
    assert not shapes.staged_float_constant(source, 'init_records')


def test_variants_collects_every_family():
    families = {family for family, _ in shapes.variants(SOURCE, 'init_records', 'mips', ASM)}
    assert families == set(shapes.FAMILIES)
