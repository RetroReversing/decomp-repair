from decomprepair.measured_signed_offset_helper import variants

SOURCE = '''extern s32 base;
void reset(s32 index, s32 enabled) {
    s32 offset;
    if (enabled) {
        action(base + ((index * 0x68) + 0x18C), index);
    }
    offset = (index * 0x68) + 0x18C;
    action(base + offset, index);
}
'''
TARGET = ['sll $a1, $s2, 1', 'addu $a1, $a1, $s2', 'sll $a1, $a1, 2',
          'addu $a1, $a1, $s2', 'lui $v0, %hi(base)', 'lw $v0, %lo(base)($v0)',
          'sll $a1, $a1, 3', 'addiu $a1, $a1, 0x18c', 'jal action', 'addu $a1, $v0, $a1']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         'addiu $v0, $v0, 0x18c' if i == 0 else 'nop') for i in range(55)]


def test_outlines_both_offsets():
    result = variants(SOURCE, 'reset', '', ROWS)
    assert len(result) == 1
    assert result[0][1].count('__repair_offset_helper(index)') == 2
    assert 'static inline int __repair_offset_helper' in result[0][1]


def test_requires_matching_evidence_and_pure_parameter():
    assert not variants(SOURCE, 'reset', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('offset = (index', 'index++;\n    offset = (index'), 'reset', '', ROWS)
    assert not variants(SOURCE.replace('0x68', '0x60'), 'reset', '', ROWS)
    assert not variants(SOURCE, 'reset', '#define __repair_offset_helper 1', ROWS)
