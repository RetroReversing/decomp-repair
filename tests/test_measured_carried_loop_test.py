from decomprepair.measured_carried_loop_test import variants

SOURCE = '''void f(void *obj) {
    s32 flag;
    s32 mode;
    s32 carry;
    u32 index;
    u8 count;
    count = M2C_FIELD(M2C_FIELD(&state, void **, 0x10), u8 *, 4);
    mode = M2C_FIELD(obj, s32 *, 8);
    index = 1;
    if (count != 0) {
        flag = (mode != 0) & (mode != 3);
        carry = 1U < 2U;
        do {
            if (carry == 0) {
                if (flag != 0) { goto body; }
            } else {
body:
                M2C_FIELD(&result, s32 *, 0x20) = update(obj, index & 0xFF);
                next(obj);
            }
            index += 1;
            carry = index < 2U;
        } while (count >= index);
    }
}'''
TARGET = ['and $s3, $v1, $v0','move $s2, $a0','sltiu $v0, $s0, 2',
          'bnez $v0, 0x60','move $a0, $s1','beql $s3, $zero, 0x7c',
          'addiu $s0, $s0, 1','move $a0, $s1','jal update']
CANDIDATE = ['and $s3, $v1, $v0','addiu $v1, $zero, 1','move $s2, $a0',
             'bnez $v1, 0x5c','move $a0, $s1','beql $s3, $zero, 0x78',
             'addiu $s0, $s0, 1','jal update']
ROWS = [('r',line,'') for line in TARGET] + [('r','',line) for line in CANDIDATE]


def test_recover_counted_loop_from_carried_first_iteration_test():
    result = variants(SOURCE,'f','',ROWS)
    assert len(result)==1
    fixed=result[0][1]
    assert 'for (index = 1; index <= count; index++)' in fixed
    assert 'index < 2U || ((mode != 0) & (mode != 3))' in fixed
    assert 'update(obj, index & 0xFF)' in fixed
    assert 'goto body' not in fixed


def test_requires_complete_source_and_target_evidence():
    assert not variants(SOURCE,'f','',[])
    assert not variants(SOURCE.replace('carry = 1U < 2U;', 'carry = 0;'),'f','',ROWS)
    assert not variants(SOURCE.replace('index += 1;', 'index += 2;'),'f','',ROWS)
    assert not variants(SOURCE,'f','#define mode value',ROWS)
    assert not variants(SOURCE.replace('goto body;', 'goto body; extra();'),'f','',ROWS)
