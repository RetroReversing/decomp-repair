from decomprepair.switch_pointer_calls import rewrite, variants

SOURCE = '''
M2C_UNK consume(void *, s32, s32);
extern M2C_UNK data_bank;
void dispatch(s32 arg0, s32 arg1, s32 arg2, s32 arg3) {
    s32 kind;
    s32 row;
    u32 selector;
    void *dest;
    row = arg2;
    selector = arg1 & 0xFF;
    switch (selector) {
    case 0:
    case 1:
    case 2:
    case 3:
    case 4:
    case 5:
        kind = arg0 & 0xFF;
        row = *(&data_bank + 0xA0 + ((arg1 & 0xFF) * 4)) + ((row & 0xFF) * 0x2C4);
        dest = row + (((arg3 & 0xFF) << 6) + 0x2C);
send:
        consume(dest, kind, row);
        break;
    case 22:
        dest = ((arg3 & 0xFF) << 6) + (&data_bank + 0x100);
load_kind:
        kind = arg0 & 0xFF;
        goto send;
    case 23:
        dest = ((arg3 & 0xFF) << 6) + (&data_bank + 0x200);
        goto load_kind;
    case 24:
        dest = &data_bank + 0x300;
        kind = arg0 & 0xFF;
        goto send;
    case 25:
        dest = &data_bank + 0x400;
        kind = arg0 & 0xFF;
        goto send;
    case 26:
        dest = &data_bank + 0x500;
        goto load_kind;
    }
}
'''
ASM = '''
addiu $sp, $sp, -0x18
addu $t0, $a0, $zero
addu $a0, $a1, $zero
andi $a1, $a0, 0xFF
sltiu $v0, $a1, 0x1B
beqz $v0, .Lexit
sw $ra, 0x10($sp)
sll $v0, $a1, 2
lui $at, %hi(jtbl_80002000)
addu $at, $at, $v0
lw $v0, %lo(jtbl_80002000)($at)
jr $v0
nop
.Lindexed:
andi $a1, $t0, 0xFF
andi $a0, $a0, 0xFF
sll $a0, $a0, 2
andi $v1, $a2, 0xFF
sll $v0, $v1, 1
addu $v0, $v0, $v1
sll $v0, $v0, 2
subu $v0, $v0, $v1
sll $v0, $v0, 4
lui $a2, %hi(data_bank + 0xA0)
addu $a2, $a2, $a0
lw $a2, %lo(data_bank + 0xA0)($a2)
addu $v0, $v0, $v1
sll $v0, $v0, 2
andi $a0, $a3, 0xFF
sll $a0, $a0, 6
addiu $a0, $a0, 0x2C
addu $a2, $a2, $v0
j .Lcall
addu $a0, $a2, $a0
.Larm22:
andi $a0, $a3, 0xFF
sll $a0, $a0, 6
lui $v0, %hi(data_bank + 0x100)
addiu $v0, $v0, %lo(data_bank + 0x100)
j .Lload_kind
addu $a0, $a0, $v0
.Larm23:
andi $a0, $a3, 0xFF
sll $a0, $a0, 6
lui $v0, %hi(data_bank + 0x200)
addiu $v0, $v0, %lo(data_bank + 0x200)
j .Lload_kind
addu $a0, $a0, $v0
.Larm24:
lui $a0, %hi(data_bank + 0x300)
addiu $a0, $a0, %lo(data_bank + 0x300)
j .Lcall
andi $a1, $t0, 0xFF
.Larm25:
lui $a0, %hi(data_bank + 0x400)
addiu $a0, $a0, %lo(data_bank + 0x400)
j .Lcall
andi $a1, $t0, 0xFF
.Larm26:
lui $a0, %hi(data_bank + 0x500)
addiu $a0, $a0, %lo(data_bank + 0x500)
.Lload_kind:
andi $a1, $t0, 0xFF
.Lcall:
jal consume
nop
.Lexit:
lw $ra, 0x10($sp)
jr $ra
addiu $sp, $sp, 0x18
'''
DATA = ('dlabel jtbl_80002000\n' + '.word .Lindexed\n' * 6 + '.word .Lexit\n' * 16
        + ''.join(f'.word .Larm{arm}\n' for arm in range(22, 27)))


def test_shared_switch_call_recovers_typed_pointer_and_byte_arguments():
    fixed = rewrite(SOURCE, 'dispatch', ASM, DATA)
    assert 'void consume(unsigned char *, unsigned char);' in fixed
    assert 'unsigned char __m2c_dispatch_bank = arg1 & 255;' in fixed
    assert ' + __m2c_dispatch_row * 708 + ' in fixed
    assert 'consume(data_bank + 512 + (__m2c_dispatch_column << 6), __m2c_dispatch_mode);' in fixed
    assert 'goto ' not in fixed


def test_shared_switch_call_requires_unchanged_table_and_prototype():
    assert not rewrite(SOURCE, 'dispatch', ASM, DATA.replace('.word .Lexit', '.word .Larm24', 1))
    assert not rewrite(SOURCE, 'dispatch', ASM.replace('jal consume', 'jal other'), DATA)
    assert not rewrite(SOURCE, 'dispatch', ASM, DATA, 'void consume(void *);')


def test_compiled_draft_reads_only_the_bounded_switch_table():
    labels = ('.Lindexed', '.Lexit', *(f'.Larm{case}' for case in range(22, 27)))
    addresses = {label: 0x80001000 + index * 4 for index, label in enumerate(labels)}
    asm = ASM
    for label, address in addresses.items():
        asm = asm.replace(label + ':\n', f'{label}:\n/* 0 {address:08X} 00000000 */ ')
    words = [addresses[entry.split()[1]] for entry in DATA.splitlines()[1:]]
    table = b''.join(word.to_bytes(4, 'big') for word in words)

    def read(symbol, size):
        assert (symbol, size) == ('jtbl_80002000', len(table))
        return table

    [(kind, fixed)] = variants(SOURCE, 'dispatch', asm, '', read_data=read, big_endian=True)
    assert kind == 'masked_switch_pointer_calls'
    assert 'void consume(unsigned char *, unsigned char);' in fixed
    assert not variants(SOURCE, 'dispatch', asm, '', read_data=read, big_endian=False)
