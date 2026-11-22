from decomprepair.rejected_branch_default import FAMILY, variants

SOURCE = """
void classify(s32 low, s32 high, s32 final)
{
    s32 var_s0;
    f32 value;
    var_s0 = 1;
    if (sample() <= 0.1f)
    {
        value = 0.0f;
        store(value);
    }
    else
    {
        observe();
        var_s0 = 1;
        if (!(low & high))
        {
            observe();
            var_s0 = 1;
            if (final)
            {
                var_s0 = 2;
            }
        }
    }
    use(var_s0);
}
"""

ROWS = [
    (' ', 'bc1f .Ltested', 'bc1f .Ltested'),
    (' ', 'addiu $s0, $zero, 1', 'addiu $s0, $zero, 1'),
    (' ', 'and $v0, $v0, $v1', 'and $v0, $v0, $v1'),
    ('i', 'bnez $v0, .Ldone', 'bnez $v0, .Lprior'),
    ('o', 'addiu $s0, $zero, 1', 'nop'),
    (' ', 'and $v0, $v0, $v1', 'and $v0, $v0, $v1'),
    ('i', 'bnez $v0, .Ldone', 'bnez $v0, .Lprior'),
    ('<', 'addiu $s0, $zero, 1', ''),
]


def test_sinks_default_to_the_arms_and_keeps_the_other_definition():
    [(family, revised)] = variants(SOURCE, 'classify', ROWS)
    assert family == FAMILY
    assert revised.index('if (sample()') < revised.index('var_s0 = 1;')
    assert 'value = 0.0f;\n        var_s0 = 1;' in revised
    assert 'if (low & high) {\n          var_s0 = 1;' in revised
    assert revised.count('var_s0 = 1;') == 3
    assert variants(revised, 'classify', ROWS) == []


def test_requires_a_definition_on_the_other_path():
    missing = SOURCE.replace('            var_s0 = 1;\n            if (final)', '            if (final)')
    premature = SOURCE.replace('        value = 0.0f;', '        value = var_s0;')
    abrupt = SOURCE.replace('            observe();', '            if (final) return;')
    for lookalike in (missing, premature, abrupt):
        assert variants(lookalike, 'classify', ROWS) == []


def test_requires_both_measured_delay_slots():
    assert variants(SOURCE, 'classify', ROWS[:-1]) == []
    assert variants(SOURCE, 'classify', [(' ', row, row) for _, row, _ in ROWS]) == []
    assert variants(SOURCE, 'classify', ROWS, header='typedef volatile int s32;') == []
