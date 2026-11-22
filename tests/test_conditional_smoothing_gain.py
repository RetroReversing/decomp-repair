"""Rebind both branch literals and only their affected blend operand."""

from decomprepair.conditional_smoothing_gain import FAMILY, variants

SOURCE = """\
f32 sample(s32 port, s32 x, s32 y);
void update(char *record, s32 port, s32 mode, f32 axis)
{
    f32 holder;
    f32 gain;
    f32 current;
    f32 next;
    if (mode) {
        gain = 0.25f;
    } else {
        gain = 0.5f;
    }
    current = *((f32 *) (((char *) record) + 0x18));
    next = ((axis - current) * gain) + current;
    report(next);
    holder = sample(port, 2, 3) * 0.75f;
    report(holder);
}
"""

DEMAND = [
    'lui $at, 0x3e80', 'ori $at, $at, 0', 'mtc1 $at, $f24',
    'j .Lblend', 'nop',
    'lui $at, 0x3f00', 'ori $at, $at, 0', 'mtc1 $at, $f24',
    'lwc1 $f0, 0x18($s0)', 'sub.s $f2, $f26, $f0',
    'mul.s $f2, $f2, $f24', 'add.s $f12, $f2, $f0',
]
DEMAND = [('r' if '$f24' in op else ' ', op, op.replace('$f24', '$f20')) for op in DEMAND]
DONOR = [(' ', op, op) for op in [
    'addiu $a1, $zero, 2', 'jal sample', 'addiu $a2, $zero, 3',
    'lui $at, 0x3f40', 'ori $at, $at, 0', 'mtc1 $at, $f2', 'nop',
    'mul.s $f24, $f0, $f2', *(['nop'] * 10),
]]
ROWS = DEMAND + DONOR


def test_reuses_the_witnessed_saved_holder_on_both_paths():
    [(label, candidate)] = variants(SOURCE, 'update', ROWS)
    assert label == FAMILY
    assert 'holder = 0.25f;' in candidate
    assert 'holder = 0.5f;' in candidate
    assert 'next = ((axis - current) * holder) + current;' in candidate


def test_checks_reaching_writes_liveness_and_the_assembly_pair():
    assert not variants(SOURCE, 'update', DEMAND)
    assert not variants(SOURCE.replace('0.25f', '0.125f'), 'update', ROWS)
    assert not variants(SOURCE.replace('0x18', '0x20'), 'update', ROWS)
    assert not variants(SOURCE.replace('        gain = 0.5f;', '        gain = axis;'), 'update', ROWS)
    assert not variants(SOURCE.replace('report(next);', 'report(next, gain);'), 'update', ROWS)
    assert not variants(SOURCE.replace('report(next);', 'report(next, holder);'), 'update', ROWS)
    bypass = SOURCE.replace('        gain = 0.25f;', '        gain = 0.25f;\n        if (mode == 2) goto other;')
    bypass = bypass.replace('    report(next);', '    goto finish;\n    other: report(gain);\n    finish: ;')
    assert not variants(bypass, 'update', ROWS)


def test_emits_group_and_bounded_alternatives_if_allocator_interference_is_possible():
    start = SOURCE.index('    if (mode)')
    end = SOURCE.index('    holder = sample(')
    second = SOURCE[start:end].replace('gain', 'other')
    combined = SOURCE[:end] + second + SOURCE[end:]
    combined = combined.replace('    f32 gain;', '    f32 gain;\n    f32 other;')
    candidates = variants(combined, 'update', DEMAND * 2 + DONOR)
    assert [code.count(' * holder)') for _, code in candidates] == [2, 1, 1]


CAPTURE_SOURCE = SOURCE.replace('    f32 holder;', '''\
    typedef struct { f32 value; } LocalRecord;
    f32 holder;
    f32 snapshot;
    f32 scaled;''').replace('    if (mode) {', '''\
    gain = magnitude(axis);
    if (probe(record)) {
        snapshot = *((f32 *) (((char *) record) + 0x24));
        notify(record);
        *((f32 *) (((char *) record) + 0x24)) = snapshot;
    } else {
        scaled = gain * 5.0f;
        report(scaled);
    }
    if (mode) {''')
CAPTURE_ROWS = [
    (' ', 'jal magnitude', 'jal magnitude'),
    (' ', 'nop', 'nop'),
    ('r', 'mov.s $f24, $f0', 'mov.s $f20, $f0'),
    (' ', 'lwc1 $f20, 0x24($s0)', 'lwc1 $f20, 0x24($s0)'),
    (' ', 'jal notify', 'jal notify'),
    (' ', 'nop', 'nop'),
    (' ', 'swc1 $f20, 0x24($s0)', 'swc1 $f20, 0x24($s0)'),
]


def _paired(code, rows):
    return [text for label, text in variants(code, 'update', rows)
            if label == 'split_capture_and_conditional_gain']


def test_splits_the_earlier_capture_when_the_gain_rebind_alone_changes_scheduling():
    [candidate] = _paired(CAPTURE_SOURCE, CAPTURE_ROWS + ROWS)
    assert 'snapshot = magnitude(axis);' in candidate
    assert 'scaled = snapshot * 5.0f;' in candidate
    assert 'holder = 0.25f;' in candidate and 'holder = 0.5f;' in candidate
    assert 'next = ((axis - current) * holder) + current;' in candidate
    assert '*((f32 *) (((char *) record) + 0x24)) = snapshot;' in candidate


def test_paired_variant_requires_the_saved_field_and_a_single_reaching_capture():
    assert not _paired(CAPTURE_SOURCE, ROWS)
    assert not _paired(CAPTURE_SOURCE, CAPTURE_ROWS[:-1] + ROWS)
    for source in (
        CAPTURE_SOURCE.replace('    gain = magnitude(axis);', '    if (mode) gain = magnitude(axis);'),
        CAPTURE_SOURCE.replace('    if (probe(record)) {', '    if (probe(record)) {\n        report(snapshot);'),
        CAPTURE_SOURCE.replace('        scaled = gain *', '        snapshot = axis;\n        scaled = gain *'),
        CAPTURE_SOURCE.replace('        scaled = gain *', '        report(gain);\n        scaled = gain *'),
        CAPTURE_SOURCE.replace('record) + 0x24)) = snapshot;', 'record) + 0x28)) = snapshot;'),
    ):
        assert not _paired(source, CAPTURE_ROWS + ROWS)
