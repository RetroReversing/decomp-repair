"""Both measured sites are required, and a carried float must be zero on every path."""

from test_balanced_float_predicate_return import ROWS as PREDICATE_ROWS

from decomprepair.balanced_predicate_projection import FAMILY, variants

SOURCE = '''
void adjust(void *record, float angle, int bypass)
{
    float phase;
    float vertical;
    int upper;
    int lower;
    vertical = 0.0f;
    phase = *((f32 *) (((char *) record) + 8));
    upper = 1;
    if (!(phase <= 0.0002f)) {
        upper = 0;
    }
    lower = 1;
    if (!(phase >= (-0.0002f))) {
        lower = 0;
    }
    if (((lower ^ 1) | (upper ^ 1)) != 0) {
        mark(record);
    }
    project:
    vertical = 0.0f + (phase * cosine(angle));
    report(vertical);
}
'''
EARLY = [('r', 'lwc1 $f26, 8($s1)', 'lwc1 $f20, 8($s1)')] + PREDICATE_ROWS[:24]
LATE = [
    (' ', 'beqz $v0, .Lprojection', 'beqz $v0, .Lprojection'),
    (' ', 'nop', 'nop'),
    (' ', 'jal cosine', 'jal cosine'),
    (' ', 'nop', 'nop'),
    ('r', 'mul.s $f0, $f26, $f0', 'mul.s $f0, $f20, $f0'),
    ('<', 'mtc1 $s6, $f16', ''),
    (' ', 'nop', 'nop'),
    ('r', 'add.s $f16, $f16, $f0', 'add.s $f0, $f0, $f24'),
    ('r', 'mfc1 $s6, $f16', 'mfc1 $s6, $f0'),
]
ROWS = EARLY + LATE


def test_balances_the_predicate_stage_with_one_proven_zero_accumulator():
    [(family, changed)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 'repair_early_fold = upper ^ 1;\n    lower = 1;' in changed
    assert 'repair_early_fold | (lower ^ 1)' in changed
    assert 'vertical += (phase * cosine(angle));' in changed
    assert not variants(SOURCE, 'adjust', EARLY)
    assert not variants(SOURCE, 'adjust', LATE)


def test_only_uses_positive_zero_that_reaches_every_incoming_path():
    assert not variants(SOURCE.replace('vertical = 0.0f;', 'vertical = -0.0f;'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('vertical = 0.0f;', 'if (bypass) goto project;\n    vertical = 0.0f;'),
                        'adjust', ROWS)
    assert not variants(SOURCE.replace('project:', 'if (bypass) vertical = 1.0f;\n    project:'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('report(vertical);', 'report(vertical);\n    if (bypass) goto project;'),
                        'adjust', ROWS)
    assert not variants(SOURCE.replace('mark(record);', 'mark(&vertical);'), 'adjust', ROWS)


def test_accepts_a_proven_zero_word_with_an_ordinary_pointer_parameter():
    source = SOURCE.replace(
        '    vertical = 0.0f;',
        '    union { u32 bits; f32 number; } zero;\n'
        '    zero.bits = (u32)record & ~(u32)record;\n'
        '    vertical = zero.number;',
    )
    [(_, changed)] = variants(source, 'adjust', ROWS)
    assert 'vertical += (phase * cosine(angle));' in changed
    assert not variants(source.replace('~(u32)record', '~(u32)angle'), 'adjust', ROWS)
    assert not variants(source.replace('void *record', 'void *volatile record'), 'adjust', ROWS)
    assert not variants(source.replace('vertical = zero.number;', 'hook(&zero);\n    vertical = zero.number;'),
                        'adjust', ROWS)
