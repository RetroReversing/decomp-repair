from decomprepair.measured_case_float_sign import FAMILY, variants

SOURCE = '''
extern float step;
void f(int kind) {
    switch (kind) {
    case 1: step = 1.5f; break;
    case 2: step = -1.5f; break;
    }
}
'''


def rows():
    return [
        ('i', 'lui $at, 0xbfc0', 'lui $at, 0x3fc0'),
        (' ', 'ori $at, $at, 0x0', 'ori $at, $at, 0x0'),
        (' ', 'mtc1 $at, $f0', 'mtc1 $at, $f0'),
        ('i', 'lui $at, 0x3fc0', 'lui $at, 0xbfc0'),
        (' ', 'ori $at, $at, 0x0', 'ori $at, $at, 0x0'),
        (' ', 'mtc1 $at, $f0', 'mtc1 $at, $f0'),
    ]


def test_exchanges_one_unique_pair_of_opposite_signs():
    [(family, source)] = variants(SOURCE, 'f', rows())
    assert family == FAMILY
    assert 'case 1: step = -1.5f;' in source
    assert 'case 2: step = 1.5f;' in source


def test_rejects_unpaired_or_ambiguous_evidence():
    assert variants(SOURCE, 'f', rows()[:3]) == []
    assert variants(SOURCE.replace('case 2:', 'case 3: step = 1.5f; break;\n    case 2:'), 'f', rows()) == []
    changed = rows()
    changed[5] = ('r', 'mtc1 $at, $f0', 'mtc1 $at, $f2')
    assert variants(SOURCE, 'f', changed) == []
