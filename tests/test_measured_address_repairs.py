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
