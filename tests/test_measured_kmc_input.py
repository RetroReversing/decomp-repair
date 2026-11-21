import pytest

from decomprepair.measured_kmc_input import variants


def diff(code, edits, extras=()):
    return [(('r' if line in edits else ' '), line, edits.get(line, line))
            for line in code.strip().splitlines()] + [('>', '', line) for line in extras]


@pytest.mark.parametrize('floating', [False, True])
def test_three_byte_cursor_types_the_incoming_pointer(floating):
    head = '''
lbu $v0, ($a1)
addiu $a1, $a1, 1
sb $v0, 8($a0)
lbu $v0, ($a1)
addiu $a1, $a1, 1
sb $v0, 9($a0)
lbu $v0, ($a1)
'''
    tail = '''
lui $at, %hi(scale)
ldc1 $f2, %lo(scale)($at)
mtc1 $v0, $f0
nop
cvt.s.w $f0, $f0
neg.s $f0, $f0
cvt.d.s $f0, $f0
mul.d $f0, $f0, $f2
addiu $v0, $a1, 1
cvt.s.d $f0, $f0
jr $ra
swc1 $f0, 12($a0)
''' if floating else 'sb $v0, 10($a0)\njr $ra\naddiu $v0, $a1, 1'
    operation = (
        'M2C_FIELD(item, f32 *, 12) = (f32) ((f64) -(f32) M2C_FIELD(next, u8 *, 1) * scale);'
        if floating else 'M2C_FIELD(item, u8 *, 10) = (u8) M2C_FIELD(next, u8 *, 1);'
    )
    source = f'''
void *f(void *item, void *bytes) {{
    void *next;
    next = bytes + 1;
    M2C_FIELD(item, u8 *, 8) = (u8) M2C_FIELD(bytes, u8 *, 0);
    M2C_FIELD(item, u8 *, 9) = (u8) M2C_FIELD(bytes, u8 *, 1);
    {operation}
    return next + 1 + 1;
}}
'''
    rows = diff(head + tail, {'addiu $a1, $a1, 1': '', 'addiu $v0, $a1, 1': 'addiu $v0, $a1, 3'})
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_three_byte_input_cursor'
    assert 'u8 *bytes)' in fixed
    assert fixed.count('*bytes++') == 3
    assert 'return bytes;' in fixed
    assert not variants(source, 'f', 'void *f(void *, void *);', rows)
    assert not variants(source.replace('next + 1 + 1', 'next + 1'), 'f', '', rows)


def test_wrapper_forwards_context_and_uses_a_byte_parameter():
    rows = diff('''
move $s0, $a0
sw $s7, 68($sp)
move $s7, $a1
sw $fp, 72($sp)
move $fp, $a2
sw $s6, 64($sp)
sw $ra, 76($sp)
jal get
move $s6, $a3
lw $a1, 16($v0)
move $a0, $s0
move $a2, $fp
andi $a3, $s6, 255
addiu $v1, $a1, 8
sw $v1, 16($v0)
sw $v0, ($a1)
sw $v0, 4($a1)
move $a1, $s7
sw $s1, 16($sp)
jal draw
sw $s5, 32($sp)
''', {'move $s0, $a0': 'move $s5, $a0', 'move $s6, $a3': 'move $fp, $a3'})
    source = '''
void *get();
void f(s32 id, M2C_UNK p, M2C_UNK q, s32 r, u8 g, u8 b, u8 a, u8 x, u8 y) {
    void *cursor;
    void *context;
    context = get();
    cursor = M2C_FIELD(context, void **, 16);
    M2C_FIELD(context, void **, 16) = (void *) (cursor + 8);
    M2C_FIELD(cursor, s32 *, 0) = 0xFF000000;
    M2C_FIELD(cursor, s32 *, 4) = -1;
    draw(id, p, q, r & 0xFF, (s32) g, (s32) b, (s32) a, (s32) x, (s32) y);
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_narrow_forwarded_call_argument'
    assert 'get(id);' in fixed and 'u8 r,' in fixed and 'draw(id, p, q, r,' in fixed
    assert not variants(source.replace('void *get();', 'void *get(void);'), 'f', '', rows)


def test_record_uses_an_address_verified_table_symbol_and_wide_index():
    rows = diff('''
jal prepare
move $s0, $a0
lui $v1, %hi(root)
lw $v1, %lo(root)($v1)
sb $s0, 8($v1)
lui $a0, %hi(table)
lw $a0, %lo(table)($a0)
lui $v0, %hi(begin)
addiu $v0, $v0, %lo(begin)
sw $v0, 16($v1)
lui $v0, %hi(end)
addiu $v0, $v0, %lo(end)
sw $v0, 20($v1)
lui $v1, %hi(root)
lw $v1, %lo(root)($v1)
addu $a0, $a0, $s0
lbu $v0, 6($a0)
sb $v0, 9($v1)
lui $v1, %hi(root)
lw $v1, %lo(root)($v1)
lbu $a0, 8($v1)
move $v0, $zero
sb $a0, 10($v1)
''', {}, ['andi $s0, $s0, 255'])
    source = '''
extern void *root;
extern M2C_UNK owner;
s32 f(u8 arg) {
    prepare();
    M2C_FIELD(root, u8 *, 8) = arg;
    M2C_FIELD(root, M2C_UNK **, 16) = &begin;
    M2C_FIELD(root, M2C_UNK **, 20) = &end;
    M2C_FIELD(root, u8 *, 9) = (u8) M2C_FIELD((M2C_FIELD(&owner, s32 *, 44) + arg), u8 *, 6);
    M2C_FIELD(root, u8 *, 10) = (u8) M2C_FIELD(root, u8 *, 8);
    return 0;
}
'''
    symbols = {'owner': 1000, 'table': 1044}
    [(label, fixed)] = variants(source, 'f', '', rows, symbols.get)
    assert label == 'measured_indexed_callback_record'
    assert 'extern char *table;' in fixed and 's32 f(s32 arg)' in fixed
    assert '__repair_record = root;' in fixed and '__repair_table = table;' in fixed
    assert not variants(source, 'f', '', rows, {'owner': 1000, 'table': 1048}.get)
    assert not variants(source, 'f', '', rows)


def test_mask_reuses_an_entry_alias_for_three_fields():
    rows = diff('''
lui $v1, %hi(global)
lw $v1, %lo(global)($v1)
andi $a0, $a0, 255
sll $v0, $a0, 3
subu $v0, $v0, $a0
sll $v0, $v0, 3
sw $ra, 16($sp)
addu $a3, $v1, $v0
lw $v0, 32($a3)
move $a2, $a1
lw $v1, 36($a3)
and $v0, $a2, $v0
and $v1, $a2, $v1
beqz $v1, 64
sltu $a1, $zero, $v0
lw $v0, 68($a3)
and $v0, $a2, $v0
move $v1, $a3
lw $v0, 72($v1)
and $v0, $a2, $v0
lw $v0, 76($v1)
and $v0, $a2, $v0
lw $v0, 80($v1)
jal apply
nop
''', {'move $v1, $a3': ''})
    source = '''
void f(s32 slot, s32 pressed) {
    s32 index;
    s32 bits;
    void *entry;
    index = slot & 0xFF;
    entry = (void *)(global); entry = (void *)((char *)entry + (s32)((index * 56)));
    bits = (pressed & M2C_FIELD(entry, s32 *, 32)) != 0;
'''
    source += ''.join(f'    if (pressed & M2C_FIELD(entry, s32 *, {offset})) {{ bits |= {1 << idx}; }}\n'
                      for idx, offset in enumerate(range(36, 88, 4), 1))
    source += '    apply(index, bits, pressed, entry);\n}\n'
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_mask_word_inputs'
    assert fixed.index('__repair_base = (void *)global;') < fixed.index('index = slot & 0xFF;')
    assert 'M2C_FIELD(entry, u32 *, 32)' in fixed
    assert fixed.count('__repair_alias = entry;') == 2
    assert fixed.count('M2C_FIELD(__repair_alias,') == 3
    assert not variants(source.replace('76))', '77))'), 'f', '', rows)
