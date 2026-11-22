from decomprepair.measured_kmc_halfword_count_loop import variants

SOURCE = '''
extern M2C_UNK counts;
extern M2C_UNK records;
extern u16 start;
void f(s32 arg) {
    s32 temp;
    s32 i;
    i = 0;
    if (*(&counts + ((arg & 0xFFFF) * 2)) != 0) {
        do {
            consume(((start + temp) * 0x64) + &records, temp);
            temp = i & 0xFFFF;
            i += 1;
        } while ((u32) (i & 0xFFFF) < (u16) *(((arg & 0xFFFF) * 2) + &counts));
    }
}'''
TARGET = [
    'andi $v0, $a0, 0xffff', 'sll $v0, $v0, 1', 'lui $at, %hi(counts)',
    'addu $at, $at, $v0', 'lhu $v0, %lo(counts)($at)', 'beqz $v0, 0x90',
    'lui $s2, %hi(records)', 'addiu $s2, $s2, %lo(records)',
    'andi $v0, $a0, 0xffff', 'lui $v1, %hi(counts)', 'addiu $v1, $v1, %lo(counts)',
    'sll $v0, $v0, 1', 'addu $s1, $v0, $v1',
    'lui $v0, %hi(start)', 'lhu $v0, %lo(start)($v0)',
    'andi $a1, $s0, 0xffff', 'addu $v0, $v0, $a1', 'sll $a0, $v0, 1',
    'addu $a0, $a0, $v0', 'sll $a0, $a0, 3', 'addu $a0, $a0, $v0',
    'sll $a0, $a0, 2', 'jal consume', 'addu $a0, $a0, $s2',
    'lhu $v1, ($s1)', 'sltu $v0, $v0, $v1', 'bnez $v0, 0x4c',
]
ROWS = [('r', line, '') for line in TARGET]


def test_reconstruct_count_width_address_scaling_and_old_index():
    result = variants(SOURCE,'f','',ROWS)
    assert len(result)==1
    fixed=result[0][1]
    assert '*(u16 *)((char *)&counts + ((arg & 0xFFFF) * 2))' in fixed
    assert '(char *)&records' in fixed
    assert 'start + (i & 0xFFFF)' in fixed
    assert 's32 temp;' not in fixed


def test_requires_matching_evidence_and_uninitialized_shape():
    assert not variants(SOURCE,'f','',[])
    assert not variants(SOURCE.replace('0x64','0x68'),'f','',ROWS)
    assert not variants(SOURCE.replace('s32 temp;', 's32 temp = 0;'),'f','',ROWS)
    assert not variants(SOURCE,'f','#define consume(x,y) other(x,y)',ROWS)
    assert not variants(SOURCE,'f','',ROWS[:-3])
    bad = [('r',line.replace('%hi(counts)','%hi(other)',1) if line.startswith('lui $v1') else line,'')
           for _,line,_ in ROWS]
    assert not variants(SOURCE,'f','',bad)
