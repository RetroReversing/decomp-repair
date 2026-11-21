from decomprepair.measured_halfword_switch import variants


def test_indexed_switch_uses_halfword_load_and_store():
    ops = '''
andi $v1, $a1, 65535
sll $v0, $v1, 1
addu $v0, $v0, $v1
sll $v0, $v0, 3
addu $v0, $v0, $v1
sll $v0, $v0, 2
lui $v1, %hi(table)
addu $v1, $v1, $v0
lhu $v1, %lo(table)($v1)
addiu $v0, $zero, 1
lui $at, %hi(table)
addu $at, $at, $v1
j f+120
sh $v0, %lo(table)($at)
'''.strip().splitlines()
    rows = [(' ', op, op) for op in ops] + [(' ', 'nop', 'nop')] * 40
    rows[5] = ('i', ops[5], 'sll $v0, $v0, 4')
    rows[13] = ('|', ops[13], 'sw $v0, %lo(table)($at)')
    source = '''
extern M2C_UNK table;
void f(void *ctx, s32 index) {
    u16 state;
    state = *(&table + ((index & 0xFFFF) * 0x64));
    switch (state) {
    case 0:
        *(&table + ((index & 0xFFFF) * 0x64)) = 1;
        return;
    case 1:
        run(ctx);
    }
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_halfword_switch_stride'
    assert fixed.count('*(u16 *)((char *)&table + ((index & 0xFFFF) * 0x64))') == 2
    assert not variants(source.replace(' = 1;', ' = 2;'), 'f', '', rows)
    assert not variants(source.replace('* 0x64', '* 0x60'), 'f', '', rows)
