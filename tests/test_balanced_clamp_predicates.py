"""The paired clamped read and predicate stage need both compiler witnesses."""

from test_balanced_float_predicate_return import ROWS as PREDICATE_ROWS

from decomprepair.balanced_clamp_predicates import FAMILY, _source_within_limit, variants

SOURCE = '''
void adjust(char *record, float axis)
{
    f32 current;
    f32 bound;
    int upper;
    int lower;
    current = *((f32 *) (((char *) record) + 8));
    bound = -0.5f;
    if ((current < (-0.5f)) || ((bound = 0.5f, current > 0.5f))) {
        *((f32 *) (((char *) record) + 8)) = bound;
    }
    upper = 1;
    if (!(axis <= 0.0002f)) {
        upper = 0;
    }
    lower = 1;
    if (!(axis >= (-0.0002f))) {
        lower = 0;
    }
    if (((lower ^ 1) | (upper ^ 1)) != 0) {
        report();
    }
}
'''
LOAD = 'lwc1 $f0, 8($s1)'
CLAMP_ROWS = [
    ('o', LOAD, ''),
    (' ', 'lui $at, 0xbf00', 'lui $at, 0xbf00'),
    (' ', 'ori $at, $at, 0', 'ori $at, $at, 0'),
    (' ', 'mtc1 $at, $f2', 'mtc1 $at, $f2'),
    ('o', 'nop', LOAD),
    (' ', 'c.lt.s $f0, $f2', 'c.lt.s $f0, $f2'),
    (' ', 'nop', 'nop'),
    (' ', 'nop', 'nop'),
    (' ', 'bc1tl .Llower', 'bc1tl .Llower'),
    (' ', 'swc1 $f2, 8($s1)', 'swc1 $f2, 8($s1)'),
]
ROWS = CLAMP_ROWS + PREDICATE_ROWS[:24]


def test_pairs_one_split_clamp_with_one_later_staged_predicate():
    [(family, candidate)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 'if (current < (-0.5f))' in candidate
    assert 'else if (current > 0.5f)' in candidate
    assert 'record) + 8)) = -0.5f;' in candidate
    assert 'repair_late_upper = upper ^ 1;\n    lower = 1;' in candidate
    assert 'repair_late_upper | (lower ^ 1)' in candidate


def test_requires_both_evidence_sites_and_an_unobserved_clamp_temporary():
    assert not variants(SOURCE, 'adjust', CLAMP_ROWS)
    assert not variants(SOURCE, 'adjust', PREDICATE_ROWS)
    assert not variants(SOURCE.replace('0.5f', '0.25f'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('record) + 8', 'record) + 16'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('report();', 'report(bound);'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('report();', 'report(&upper);'), 'adjust', ROWS)


def test_accepts_only_token_preserving_indentation_under_the_given_budget():
    [(family, ordinary)] = variants(SOURCE, 'adjust', ROWS)
    budget = len(ordinary.encode()) - 5
    [(compact_family, compact)] = variants(SOURCE, 'adjust', ROWS, max_bytes=budget)
    assert family == compact_family
    assert compact.split() == ordinary.split()
    assert compact.count('\n') == ordinary.count('\n')
    assert len(compact.encode()) <= budget
    assert not variants(SOURCE, 'adjust', ROWS, max_bytes=1)
    assert _source_within_limit('    "text"\n', 10) is None
    assert _source_within_limit('    #if 1\n', 9) is None
    assert _source_within_limit('    a \\\n', 7) is None


def test_offers_each_witnessed_clamp_when_only_one_inversion_can_balance_it():
    start, end = SOURCE.index('    current ='), SOURCE.index('    upper = 1;')
    second = SOURCE[start:end].replace('current', 'another').replace('bound', 'other_bound').replace(
        'record) + 8', 'record) + 12',
    ).replace('0.5f', '0.25f')
    source = (SOURCE[:end] + second + SOURCE[end:]).replace(
        '    int upper;', '    f32 another;\n    f32 other_bound;\n    int upper;',
    )
    rows = [
        (marker, left.replace('0xbf00', '0xbe80').replace('8($s1)', '12($s1)'),
         right.replace('0xbf00', '0xbe80').replace('8($s1)', '12($s1)'))
        for marker, left, right in CLAMP_ROWS
    ]
    cases = [text for _, text in variants(source, 'adjust', CLAMP_ROWS + rows + PREDICATE_ROWS[:24])]
    assert len(cases) == 2
    assert 'else if (current > 0.5f)' in cases[0]
    assert 'else if (another > 0.25f)' in cases[1]
