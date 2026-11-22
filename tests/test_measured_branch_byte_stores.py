from decomprepair.measured_branch_byte_stores import variants

SOURCE = '''void paint(void *p, s32 n) {
    if (n <= 10) {
        M2C_FIELD(p, s8 *, 0x90) = 10;
        M2C_FIELD(p, s8 *, 0x92) = 10;
        M2C_FIELD(p, u8 *, 0x91) = 200;
    } else {
        M2C_FIELD(p, u8 *, 0x90) = 250;
        M2C_FIELD(p, s8 *, 0x91) = 50;
        M2C_FIELD(p, s8 *, 0x92) = 10;
    }
    M2C_FIELD(p, u8 *, 0x93) = 255;
}
'''
T = ['addiu $v0, $zero, 0xa', 'addiu $v1, $zero, 0xc8', 'sb $v0, 0x90($a0)',
     'sb $v0, 0x92($a0)', 'addiu $v0, $zero, 0xff', 'j func+0x7c', 'sb $v1, 0x91($a0)']
C = ['addiu $v0, $zero, 0xa', 'sb $v0, 0x90($a0)', 'sb $v0, 0x92($a0)',
     'addiu $v0, $zero, 0xc8', 'j func+0x74', 'sb $v0, 0x91($a0)']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(len(T))]


def test_distributes_shared_store_and_orders_first_branch():
    result = variants(SOURCE, 'paint', '', ROWS)
    assert len(result) == 1
    assert result[0][1].count('M2C_FIELD(p, u8 *, 0x93) = 255;') == 2
    assert result[0][1].index('0x91) = 200') < result[0][1].index('0x92) = 10')


def test_requires_nonoverlapping_stores_and_evidence():
    assert not variants(SOURCE, 'paint', '', [('r', x, x) for x in T])
    assert not variants(SOURCE.replace('0x93) = 255', '0x92) = 255'), 'paint', '', ROWS)
    assert not variants(SOURCE.replace('void *p', 'volatile void *p'), 'paint', '', ROWS)
    assert not variants(SOURCE.replace('0x92) = 10;', '0x92) = read();', 1), 'paint', '', ROWS)
