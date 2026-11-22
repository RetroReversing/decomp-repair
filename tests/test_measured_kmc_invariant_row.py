from decomprepair.measured_kmc_invariant_row import variants

SOURCE = '''void f(f32 *src, s32 dst) {
    char *rowptr;
    char *srcptr;
    f32 value;
    s32 col;
    s32 row;
    s32 dstptr;
    rowptr = src;
    row = 0;
    do {
        col = 0;
        srcptr = rowptr;
        dstptr = dst;
loop:
        value = *(f32 *)srcptr;
        srcptr += 4;
        col += 1;
        *(f32 *)((row * 4) + dstptr) = value;
        dstptr += 0x10;
        if (col < 4) { goto loop; }
        row += 1;
        rowptr += 0x10;
    } while (row < 4);
}'''
TARGET = ['move $a3, $zero','sll $t1, $t0, 2','move $a2, $a0','move $v1, $a1',
          'lwc1 $f0, ($a2)','addiu $a2, $a2, 4','addu $v0, $t1, $v1',
          'addiu $a3, $a3, 1','swc1 $f0, ($v0)']
CANDIDATE = ['move $a3, $zero','move $a2, $a0','move $v1, $a1',
             'lwc1 $f0, ($a2)','addiu $a2, $a2, 4','addiu $a3, $a3, 1',
             'sll $v0, $t0, 2','addu $v0, $v0, $v1','swc1 $f0, ($v0)']
ROWS = [('r',a,b) for a,b in zip(TARGET,CANDIDATE)]


def test_hoist_row_offset_and_advance_counter_in_condition():
    result = variants(SOURCE,'f','',ROWS)
    assert len(result)==1
    fixed = result[0][1]
    assert 'repair_row_offset = row * 4;' in fixed
    assert '(repair_row_offset + dstptr)' in fixed
    assert 'if (++col < 4)' in fixed
    assert 'col += 1;' not in fixed


def test_requires_target_shape_and_invariant_local_counter():
    assert not variants(SOURCE,'f','',[])
    assert not variants(SOURCE.replace('col += 1;', 'col += row;'),'f','',ROWS)
    assert not variants(SOURCE.replace('srcptr += 4;', 'srcptr += 4; row += 1;'),'f','',ROWS)
    assert not variants(SOURCE,'f','#define row get_row()',ROWS)
    assert not variants(SOURCE,'f','',ROWS[:-1])
