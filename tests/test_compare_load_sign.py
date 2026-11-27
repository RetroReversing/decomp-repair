from decomprepair.compare_load_sign import variants

LH = 'lh $v0, 0x2($a0)\nxori $v0, $v0, 1\n'
LHU = 'lhu $v0, 0x2($a0)\nxori $v0, $v0, 1\n'


def test_a_halfword_compare_read_as_u16_becomes_s16_when_the_target_loads_lh():
    source = 'int f(void) {\n    return (*(u16 *)(D_802083F0 + (D_800AD1A8 * 0x270)) == 1);\n}\n'
    assert variants(source, 'f', LH) == [('compare_load_sign', source.replace('u16', 's16'))]


def test_the_other_direction_and_bytes():
    assert 'u16' in variants('int f(void *p) {\n    return M2C_FIELD(p, s16 *, 2) < 5;\n}\n', 'f', LHU)[0][1]
    assert 'u8 *' in variants('int f(char *p) {\n    return 3 != *(s8 *)(p + 1);\n}\n', 'f', 'lbu $v0, 1($a0)\n')[0][1]
    assert 's8 *' in variants('int f(char *p) {\n    return *(u8 *)p >= 3;\n}\n', 'f', 'lb $v0, 0($a0)\n')[0][1]


def test_mixed_loads_give_one_child_per_read_and_unrelated_reads_stay():
    source = 'int f(u16 *p, void *q) {\n    return *(u16 *)q == 1 && *(u16 *)p == 2;\n}\n'
    texts = [t for _, t in variants(source, 'f', LH + LHU)]
    assert len(texts) == 2 and all(t.count('s16') == 1 for t in texts)


def test_nothing_when_the_target_agrees_or_the_read_is_not_compared():
    assert variants('int f(void *p) {\n    return *(s16 *)p == 1;\n}\n', 'f', LH) == []
    assert variants('int f(void *p) {\n    return *(u16 *)p + 1;\n}\n', 'f', LH) == []
    assert variants('int f(void *p) {\n    return *(u16 *)p == 1;\n}\n', 'f', 'lw $v0, 0($a0)\n') == []
