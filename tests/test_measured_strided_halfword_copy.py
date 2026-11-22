from decomprepair.measured_strided_halfword_copy import variants

SOURCE = '''u16 *owner();
extern void *scene;
void copy(u16 *input) {
    s32 row;
    s32 col;
    char *dst;
    char *src;
    src = input;
    dst = owner(scene);
    row = 0;
    if (M2C_FIELD(scene, s16 *, 6) > 0) {
        do {
            col = 0;
            if (M2C_FIELD(scene, s16 *, 4) > 0) {
                rows: {
                    *(u16 *)dst = *(u16 *)src;
                    src += 4;
                    col += 1;
                    dst += 2;
                }
                if (col < M2C_FIELD(scene, s16 *, 4)) goto rows;
            }
            row += 1;
            src += 0x500;
        } while (row < M2C_FIELD(scene, s16 *, 6));
    }
}'''
T = ['jal owner', 'lui $a0, %hi(scene)', 'lh $v1, 6($a0)', 'lh $v0, 4($a0)',
     'lhu $v0, ($s0)', 'sh $v0, ($a1)', 'addiu $s0, $s0, 4', 'addiu $a1, $a1, 2',
     'addiu $s0, $s0, 1280']
ROWS = [('r', line, '') for line in T]


def test_restores_typed_nested_copy_and_row_stride():
    label, fixed = variants(SOURCE, 'copy', '', ROWS)[0]
    assert label == 'measured_strided_halfword_copy'
    assert 'u16 *dst;' in fixed
    assert '*dst++ = *input;' in fixed
    assert 'input += 2;' in fixed
    assert 'input += 640;' in fixed


def test_requires_measured_strides_and_unmodified_source():
    assert not variants(SOURCE.replace('0x500', '0x501'), 'copy', '', ROWS)
    assert not variants(SOURCE.replace('dst += 2;', 'dst += 2; touch();'), 'copy', '', ROWS)
    assert not variants(SOURCE.replace('u16 *owner()', 's32 owner()'), 'copy', '', ROWS)
    assert not variants(SOURCE, 'copy', '#define row shared', ROWS)
    assert not variants(SOURCE, 'copy', '', ROWS[:-1])
