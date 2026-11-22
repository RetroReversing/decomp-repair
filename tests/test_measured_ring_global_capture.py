from decomprepair.measured_ring_global_capture import variants

SOURCE = '''extern void *ring;
void resume(void) {
    s32 count;
    s32 size;
    if (ring != NULL) {
        count = M2C_FIELD(ring, s32 *, 8);
        size = M2C_FIELD(ring, s32 *, 0x10);
        if (count < size) {
            use(ring, ring);
            M2C_FIELD(ring, s32 *, 8) += 1;
            use(ring, ring);
        }
    }
}
'''
TARGET = ['lui $a1, %hi(ring)', 'lw $a1, %lo(ring)($a1)', 'addiu $sp, $sp, -0x18',
          'beqz $a1, 0xa8', 'sw $ra, 0x10($sp)', 'lw $a0, 8($a1)', 'lw $v1, 0x10($a1)',
          'slt $v0, $a0, $v1', 'sw $a0, ($v1)', 'sw $v0, 8($a1)', 'lw $v1, ($a1)']
CANDIDATE = ['lui $a0, %hi(ring)', 'lui $a0, %hi(ring)', 'sw $v0, 8($a0)']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(45)]


def test_captures_the_target_pointer():
    result = variants(SOURCE, 'resume', '', ROWS)
    assert len(result) == 1
    assert '__repair_ring = ring;' in result[0][1]
    assert 'M2C_FIELD(__repair_ring, s32 *, 8)' in result[0][1]


def test_requires_matching_reads_and_safe_source():
    assert not variants(SOURCE, 'resume', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('use(ring, ring);', 'ring = NULL;'), 'resume', '', ROWS)
    assert not variants(SOURCE.replace('extern void *ring', 'extern volatile void *ring'), 'resume', '', ROWS)
    assert not variants(SOURCE.replace('count =', '/* note */ count ='), 'resume', '', ROWS)
