from decomprepair.measured_packed_quad import variants

SOURCE = '''typedef struct { int field_0; int field_4; } rec;
void pack(void *obj, s32 a, s32 b, s32 c, u16 d) {
    s32 high;
    s32 bits;
    void *cursor;
    cursor = M2C_FIELD(obj, void **, 20);
    high = (a & 0x1F) << 0x11;
    bits = (c & 0x1F) * 2;
    ((rec*)cursor)->field_0 = (s32) (high | ((b & 0x1F) << 9) | bits | 0x07000000);
    ((rec*)cursor)->field_4 = (s32) (high | (bits << 8) | ((d & 0x1F) * 2));
    M2C_FIELD(obj, void **, 20) = (void *) (M2C_FIELD(obj, void **, 20) + 8);
}'''
T = ['lw $v1, 20($a0)', 'andi $a1, $a1, 31', 'sll $a1, $a1, 17',
     'andi $a2, $a2, 31', 'sll $a2, $a2, 9', 'or $a2, $a1, $a2',
     'andi $a3, $a3, 31', 'sll $a3, $a3, 1', 'or $a2, $a2, $a3',
     'lui $v0, 1792', 'or $a2, $a2, $v0', 'sw $a2, ($v1)',
     'lhu $v0, 18($sp)', 'sll $a3, $a3, 8', 'or $a1, $a1, $a3', 'sw $v1, 20($a0)']
ROWS = [('r', op, '') for op in T]


def test_stages_bits_and_reads_low_stack_halfword():
    label, fixed = variants(SOURCE, 'pack', '', ROWS, ['-mgp32'], True)[0]
    assert label == 'measured_packed_quad'
    assert 's32 d)' in fixed
    assert '(((u16 *)&d)[1] & 0x1F)' in fixed
    assert '__repair_word = __repair_word | bits;' in fixed


def test_requires_big_endian_word_abi_and_matching_shape():
    assert not variants(SOURCE, 'pack', '', ROWS, ['-mgp32'], False)
    assert not variants(SOURCE, 'pack', '', ROWS, ['-mgp64'], True)
    assert not variants(SOURCE, 'pack', 'void pack(void *, int, int, int, u16);', ROWS, ['-mgp32'], True)
    assert not variants(SOURCE.replace('0x1F', '0x3F', 1), 'pack', '', ROWS, ['-mgp32'], True)
    assert not variants(SOURCE, 'pack', '', ROWS[:-1], ['-mgp32'], True)
