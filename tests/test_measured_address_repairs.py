from decomprepair.measured_address_repairs import variants
from decomprepair.symbols import Symbol, SymbolTable

BINDING = [
    ('i', 'lui $a0, %hi(D_80117710)', 'lui $a0, %hi(D_800B6E84+0x174)'),
    ('i', 'addiu $a0, $a0, %lo(D_80117710)', 'addiu $a0, $a0, %lo(D_800B6E84+0x174)'),
]
SWAP = [('r', 'addu $a1, $v0, $v1', 'addu $a1, $v1, $v0')]


def test_global_binding_needs_a_paired_relocation_and_known_data_target():
    source = '''extern char D_800B6FF8[];
void f(void) { send(D_800B6FF8); }
'''
    table = SymbolTable([Symbol('D_80117710', 0x80117710, kind='bss')])
    expected = ('measured_relocation_binding', source.replace('D_800B6FF8', 'D_80117710'))
    assert variants(source, 'f', '', BINDING, table) == [expected]
    assert not variants(source, 'f', '', BINDING[:1], table)
    assert not variants(source, 'f', '', BINDING, SymbolTable())
    assert not variants(source, 'f', 'extern char D_800B6FF8[];', BINDING, table)
    assert not variants(source, 'f', '', BINDING + [
        (' ', 'lui $a1, %hi(D_800B6FF8)', 'lui $a1, %hi(D_800B6FF8)'),
    ], table)
    assert not variants(source + 'void g(void) { send(D_800B6FF8); }', 'f', '', BINDING, table)


def test_swapped_operands_admit_only_the_typed_address_forms():
    source = '''extern s32 D_800BFF04;
u16 *f(int input) { s32 i; i = input; return (u16 *)(D_800BFF04+i*8); }
'''
    candidates = variants(source, 'f', '', SWAP)
    assert candidates == [('measured_address_add', source.replace('D_800BFF04+i*8','i * 8 + D_800BFF04'))]
    assert not variants(source, 'f', '', [('r', SWAP[0][1], 'addu $a1, $v0, $a0')])
    assert not variants(source.replace('i*8','compute()*8'), 'f', '', SWAP)
    assert not variants(source.replace('extern s32','extern volatile s32'), 'f', '', SWAP)


def test_pointer_table_cast_preserves_element_size_and_narrow_index():
    source = 'Object **f(int i) { Object **p = base; return &p[(u16)i]; }'
    candidates = variants(source, 'f', '', SWAP)
    assert len(candidates) == 1
    assert '(unsigned int)(u16)i * sizeof(*p)' in candidates[0][1]
    assert not variants(source.replace('(u16)i','index()'), 'f', '', SWAP)


def test_reciprocal_links_only_reorder_the_two_independent_fields():
    one, two = 'sw $v1, -0x18($v1)', 'sw $v0, 4($v1)'
    source = 'void f(int i) { a[i].prev=&a[i-1]; a[i-1].next=&a[i]; }'
    diff = [('i',one,two),('i',two,one)]
    assert variants(source,'f','',diff) == [
        ('measured_link_store_order','void f(int i) { a[i-1].next=&a[i]; a[i].prev=&a[i-1]; }'),
    ]
    assert not variants(source.replace('.next','.prev'),'f','',diff)
    assert not variants(source.replace('; a','; /* keep */ a'),'f','',diff)
    assert not variants(source,'f','',diff[:1])


def test_byte_offset_through_a_generated_global_uses_the_call_delay_slot():
    from decomprepair.measured_address_repairs import rewrite_byte_offsets

    source = 'extern M2C_UNK state;\nvoid f(void) { dispatch(&state + 0x8010); }'
    target = '''lui $a0, %hi(state + 0x8010)
jal dispatch
addiu $a0, $a0, %lo(state + (0x8010 & 0xFFFF))
'''
    fixed = rewrite_byte_offsets(source, 'f', target)
    assert fixed and 'dispatch((char *)&state + 0x8010)' in fixed
    assert rewrite_byte_offsets(fixed, 'f', target) is None
    assert rewrite_byte_offsets(source, 'f', target.replace('0x8010 &', '0x8030 &')) is None
    assert rewrite_byte_offsets(source, 'f', target.replace('jal dispatch', 'move $a0, $v0')) is None
    assert rewrite_byte_offsets(source, 'f', target, 'extern s32 state;') is None
    assert rewrite_byte_offsets(source.replace('0x8010);', '0x8010 * 4);'), 'f', target) is None


def test_address_wrapper_can_restore_the_incoming_first_argument():
    from decomprepair.measured_address_repairs import rewrite_byte_offsets

    source = '''M2C_UNK dispatch(void *); /* extern */
extern M2C_UNK state;
s32 f(void) {
    dispatch(&state + 0x40);
    return 0;
}
'''
    target = '''addiu $sp, $sp, -0x18
sw $ra, 0x10($sp)
lui $a1, %hi(state + 0x40)
jal dispatch
addiu $a1, $a1, %lo(state + 0x40)
lw $ra, 0x10($sp)
move $v0, $zero
jr $ra
addiu $sp, $sp, 0x18
'''
    patch = rewrite_byte_offsets(source, 'f', target, 'void other(s32 arg0);')
    assert patch and 's32 f(s32 arg0)' in patch
    assert 'dispatch(s32, void *);' in patch
    assert 'dispatch(arg0, (char *)&state + 0x40);' in patch
    assert rewrite_byte_offsets(source, 'f', target, 's32 dispatch(void *);') is None
    assert rewrite_byte_offsets(source, 'f', target, '#define arg0 1') is None


def test_indexed_relocation_keeps_byte_scaling_and_the_word_load():
    from decomprepair.measured_address_repairs import byte_offsets_apply, rewrite_byte_offsets

    source = 'extern M2C_UNK state;\ns32 f(s32 i) { return *(&state + 0x8200 + (i * 4)); }'
    target = '''sll $v0, $v0, 2
lui $at, %hi(state + 0x8200)
addu $at, $at, $v0
lw $v0, %lo(state + (0x8200 & 0xFFFF))($at)
'''
    assert byte_offsets_apply(target)
    fixed = rewrite_byte_offsets(source, 'f', target)
    assert fixed and '*(s32 *)((char *)&state + 0x8200 + (i * 4))' in fixed
    assert rewrite_byte_offsets(source, 'f', target.replace('sll $v0, $v0, 2', 'sll $v0, $v0, 3')) is None
    assert rewrite_byte_offsets(source, 'f', target.replace('addu $at, $at, $v0', 'addu $at, $at, $v1')) is None
    assert rewrite_byte_offsets(source, 'f', target.replace('0x8200 & 0xFFFF', '0x8240 & 0xFFFF')) is None
    assert rewrite_byte_offsets(source.replace('i * 4','i * 8'), 'f', target) is None


def test_saved_global_displacement_is_measured_in_bytes_at_one_call():
    source = ('extern M2C_UNK timer;\ns32 f(void) {\n'
              '    start(&timer);\n    return count(&timer - 8);\n}')
    rows = [(' ', op, op) for op in ('lui $s0, %hi(timer)', 'addiu $s0, $s0, %lo(timer)',
                                      'move $a0, $s0', 'jal start', 'nop', 'jal count')]
    rows += [('i', 'addiu $a0, $s0, -8', 'addiu $a0, $s0, -0x20')]
    assert variants(source, 'f', '', rows) == [
        ('measured_saved_global_call_offset', source.replace('count(&timer', 'count((u8 *)&timer'))]
    assert not variants(source, 'f', '', rows[1:])
    assert not variants(source, 'f', '', rows[:3] + [(' ', 'move $s0, $zero', 'move $s0, $zero')] + rows[3:])
    assert not variants(source, 'f', 'extern u32 timer;', rows)
    assert not variants(source.replace('- 8', '- 4'), 'f', '', rows)
