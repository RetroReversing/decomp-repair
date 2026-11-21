from decomprepair.kmc_cast_repairs import variants

LOADS = [
    ('|', 'lwc1 $f0, ($v1)', 'lbu $v0, ($v1)'),
    ('>', '', 'mtc1 $v0, $f0'),
    ('>', '', 'cvt.s.w $f0, $f0'),
    ('|', 'lw $v0, ($v1)', 'lbu $v0, ($v1)'),
]
RMW = [
    ('r', 'lui $s2, 0x2000', 'lui $v0, 0x2000'),
    (' ', 'jal action', 'jal action'),
    (' ', 'lw $v0, 0x88($s1)', 'lw $v0, 0x88($s1)'),
    ('<', 'or $v0, $v0, $s2', ''),
    (' ', 'sw $v0, 0x88($s1)', 'sw $v0, 0x88($s1)'),
]


def test_typed_load_can_bundle_two_paths_from_the_same_pointer():
    source = '''
extern f32 loaded_float;
extern s32 loaded_word;
void update(u8 *base, int select) {
    u8 *p;
    p = base;
    if (select) {
        loaded_float = (f32)*p;
    } else {
        loaded_word = (s32)*p;
    }
}
'''
    as_float = source.replace('(f32)*p', '*(f32 *)p')
    as_word = source.replace('(s32)*p', '*(s32 *)p')
    both = as_float.replace('(s32)*p', '*(s32 *)p')
    assert variants(source, 'update', '', LOADS) == [
        ('kmc_typed_load', both), ('kmc_typed_load', as_float), ('kmc_typed_load', as_word),
    ]
    assert variants(source, 'update', '', LOADS[:3]) == [('kmc_typed_load', as_float)]
    assert not variants(source, 'update', '', LOADS[:1])
    assert not variants(source, 'update', '', LOADS, ('-fstrict-aliasing',))
    assert not variants(source, 'update', '', [tuple(s.replace('($v1)', '4($v1)') if i == 1 else s
                                                   for i,s in enumerate(row)) for row in LOADS])
    assert not variants(source.replace('u8 *p;', 'volatile u8 *p;'), 'update', '', LOADS)


def test_truncated_literal_needs_a_missing_same_address_or_and_the_exact_value():
    source = 'void update(s32 *p) { *p = (s32)(*p | (unsigned short)0x20000000); }'
    assert variants(source, 'update', '', RMW) == [
        ('kmc_truncated_literal', source.replace('(unsigned short)', '')),
    ]
    assert not variants(source.replace('0x20000000','0x10000000'), 'update', '', RMW)
    assert not variants(source.replace('|', '||'), 'update', '', RMW)
    assert not variants(source, 'update', '', RMW[:-1])
    assert not variants(source, 'update', '', RMW[:3]+[(' ', RMW[3][1], RMW[3][1])]+RMW[4:])
    assert not variants(source, 'update', '', RMW[:1]+[(' ', 'move $s2, $v0', 'move $s2, $v0')]+RMW[1:])


BYTE_ARRAY_SOURCE = '''
extern char label[];
extern char table[];
s32 read(u32 index) {
    publish(label);
    return *(table + index);
}
'''
BYTE_ARRAY_LOAD = ('|', 'lbu $v0, %lo(table)($at)', 'lb $v0, %lo(table)($at)')


def test_unsigned_byte_array_uses_the_relocated_read():
    exact = BYTE_ARRAY_SOURCE.replace('extern char table', 'extern unsigned char table')
    assert variants(BYTE_ARRAY_SOURCE, 'read', '', [BYTE_ARRAY_LOAD]) == [('kmc_unsigned_byte_array', exact)]
    assert not variants(BYTE_ARRAY_SOURCE, 'read', 'extern char table[];', [BYTE_ARRAY_LOAD])
    assert not variants(BYTE_ARRAY_SOURCE.replace('publish(label)', 'publish(table)'), 'read', '', [BYTE_ARRAY_LOAD])
    assert not variants(BYTE_ARRAY_SOURCE.replace('return *(table + index);', '*(table + index) = 0;'),
                        'read', '', [BYTE_ARRAY_LOAD])
    assert not variants(BYTE_ARRAY_SOURCE, 'read', '', [
        BYTE_ARRAY_LOAD, ('r', 'move $a0, $zero', 'move $a1, $zero'),
    ])


def test_indirect_byte_array_requires_one_read_with_relocation_evidence():
    rows = [
        (' ', 'lui $a2, %hi(table)', 'lui $a2, %hi(table)'),
        (' ', 'addiu $a2, $a2, %lo(table)', 'addiu $a2, $a2, %lo(table)'),
        ('|', 'lbu $v0, ($a2)', 'lb $v0, ($a2)'),
    ]
    assert variants(BYTE_ARRAY_SOURCE, 'read', '', rows) == [
        ('kmc_unsigned_byte_array', BYTE_ARRAY_SOURCE.replace('extern char table', 'extern unsigned char table')),
    ]
    assert not variants(BYTE_ARRAY_SOURCE, 'read', '', rows[1:])
    assert not variants(BYTE_ARRAY_SOURCE, 'read', '', rows[:-1] + [('|', 'lbu $v0, ($a2)', 'lb $v0, ($a3)')])
    assert not variants(BYTE_ARRAY_SOURCE.replace('publish(label);', 'publish(*(label + index));'), 'read', '',
                        [(' ', 'lui $v1, %hi(label)', 'lui $v1, %hi(label)')] + rows)
