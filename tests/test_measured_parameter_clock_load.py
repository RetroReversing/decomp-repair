from decomprepair.measured_parameter_clock_load import variants

SOURCE = '''void setup(void *owner, void *voice) {
    s32 delay;
    void *param;
    delay = M2C_FIELD(M2C_FIELD(voice, void **, 8), s32 *, 0xd8);
    M2C_FIELD(param, s16 *, 8) = 0xb;
    M2C_FIELD(param, s32 *, 4) = (s32) (M2C_FIELD(owner, s32 *, 0x1c) + delay);
}
'''
T = ['lw $v0, 8($s1)', 'lw $v1, 0x1c($a0)', 'lw $a2, 0xd8($v0)', 'move $a1, $s3',
     'addiu $v0, $zero, 0xb', 'sh $v0, 8($s0)']
C = ['lw $v0, 8($s1)', 'lw $a2, 0xd8($v0)', 'move $a1, $s3', 'addiu $v0, $zero, 0xb',
     'sh $v0, 8($s0)', 'lw $v1, 0x1c($a0)']
ROWS = [('r', a, b) for a, b in zip(T, C)]


def test_stages_clock_before_delay():
    result = variants(SOURCE, 'setup', '', ROWS)
    assert len(result) == 1
    assert '__repair_clock = M2C_FIELD(owner, s32 *, 0x1c);' in result[0][1]
    assert '__repair_clock + delay' in result[0][1]
    assert result[0][1].index('__repair_clock =') < result[0][1].index('delay =')


def test_requires_matching_offsets_and_nonvolatile_source():
    assert not variants(SOURCE, 'setup', '', [('r', x, x) for x in T])
    assert not variants(SOURCE.replace('0xd8', '0xdc'), 'setup', '', ROWS)
    assert not variants(SOURCE.replace('void *owner', 'volatile void *owner'), 'setup', '', ROWS)
    assert not variants(SOURCE.replace('0xb;', 'get_kind();'), 'setup', '', ROWS)
