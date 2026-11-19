"""Three floats copied or passed one by one, as the record the source moved whole."""
from decomprepair import float_record_copy_repairs as f

SOURCE = '''void g(void *, f32, f32, f32);

void f(void *arg0, void *arg1, void *arg2) {
    M2C_FIELD(arg0, f32 *, 0x24) = (f32) M2C_FIELD(arg2, f32 *, 0);
    M2C_FIELD(arg0, f32 *, 0x28) = (f32) M2C_FIELD(arg2, f32 *, 4);
    M2C_FIELD(arg0, f32 *, 0x2C) = (f32) M2C_FIELD(arg2, f32 *, 8);
    g(arg0 + 0x3C, M2C_FIELD(arg1, f32 *, 0), M2C_FIELD(arg1, f32 *, 4), M2C_FIELD(arg1, f32 *, 8));
}
'''
ASM = '''lw         $v0, 0x0($a2)
lw         $a0, 0x4($a2)
lw         $a1, 0x8($a2)
sw         $v0, 0x24($s0)
sw         $a0, 0x28($s0)
sw         $a1, 0x2C($s0)
lw         $a1, 0x0($v1)
lw         $a2, 0x4($v1)
lw         $a3, 0x8($v1)
'''


def test_copied_and_passed_as_a_record():
    # An N64 function at 70%: exact so.
    (family, out), = f.variants(SOURCE, 'f', ASM)
    assert family == 'float_record_copy'
    assert out.startswith('typedef struct { f32 __repair_v[3]; } __repair_vec3;\n')
    assert '(*(__repair_vec3 *) ((s8 *) (arg0) + 0x24)) = (*(__repair_vec3 *) ((s8 *) (arg2) + 0));' in out
    assert 'g(arg0 + 0x3C, (*(__repair_vec3 *) ((s8 *) (arg1) + 0)));' in out
    assert 'void g(void *, __repair_vec3);' in out


def test_only_where_the_target_moves_words():
    assert f.variants(SOURCE, 'f', ASM.replace('sw ', 'swc1 ').replace('lw         $a', 'lwc1       $f')) == []
    assert f.variants(SOURCE, 'f', '') == []
    assert f.variants(SOURCE.replace("f32 *, 0x2C) = (f32) M2C_FIELD(arg2, f32 *, 8)",
                                     "f32 *, 0x30) = (f32) M2C_FIELD(arg2, f32 *, 8)"), 'f',
                      ASM.replace('lw         $a1, 0x0($v1)\nlw         $a2, 0x4($v1)\nlw         $a3, 0x8($v1)\n', '')) == []
