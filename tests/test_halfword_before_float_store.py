from decomprepair.halfword_before_float_store import FAMILY, variants

SOURCE = """
extern f32 scale;
int adjust(void *actor)
{
    scale = 0.6f;
    if ((*((s16 *) (((char *) (*((void **) (((char *) actor) + 20)))) + 16))) < 7)
        return 1;
    return 0;
}
"""

ROWS = [
    ('o', 'lw $v0, 20($s1)', ''),
    (' ', 'lui $at, 0x3f19', 'lui $at, 0x3f19'),
    (' ', 'ori $at, $at, 0x999a', 'ori $at, $at, 0x999a'),
    (' ', 'mtc1 $at, $f0', 'mtc1 $at, $f0'),
    ('o', 'lh $v0, 16($v0)', ''),
    (' ', 'lui $at, %hi(scale)', 'lui $at, %hi(scale)'),
    (' ', 'swc1 $f0, %lo(scale)($at)', 'swc1 $f0, %lo(scale)($at)'),
    ('o', '', 'lw $v0, 20($s1)'),
    ('o', '', 'lh $v0, 16($v0)'),
    (' ', 'slti $v0, $v0, 7', 'slti $v0, $v0, 7'),
]


def test_stages_signed_read_before_the_bound_global_store():
    [(family, revised)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 's32 repair_signed_field;' in revised
    assert revised.index('repair_signed_field =') < revised.index('scale = 0.6f;')
    assert 'if (repair_signed_field < 7)' in revised
    assert variants(revised, 'adjust', ROWS) == []


def test_requires_matching_literal_offsets_and_comparison():
    for lookalike in (SOURCE.replace('0.6f', '0.7f'), SOURCE.replace('+ 20', '+ 21'),
                      SOURCE.replace('< 7', '< 6'), SOURCE.replace('extern f32', 'extern volatile f32')):
        assert variants(lookalike, 'adjust', ROWS) == []
    assert variants(SOURCE, 'adjust', [(' ', t, t) for _, t, _ in ROWS if t]) == []
    assert variants(SOURCE, 'adjust', ROWS, header='typedef volatile short s16;') == []
