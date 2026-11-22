"""Reuse the earlier completed register lifetime for the conditional field update."""

from decomprepair.conditional_field_subtract import FAMILY, variants

SOURCE = '''
extern f32 balance;
extern u8 active;
void adjust(char *record)
{
    f32 saved;
    f32 value;
    saved = *((f32 *) (((char *) record) + 0x48));
    balance -= saved;
    value = *((f32 *) (((char *) record) + 0x48));
    if (active != 0) {
        value *= 2.0f;
    }
    balance -= value;
}
'''
ROWS = [
    (' ', 'lwc1 $f26, 0x48($s1)', 'lwc1 $f26, 0x48($s1)'),
    (' ', 'lui $at, %hi(balance)', 'lui $at, %hi(balance)'),
    (' ', 'lwc1 $f0, %lo(balance)($at)', 'lwc1 $f0, %lo(balance)($at)'),
    (' ', 'sub.s $f0, $f0, $f26', 'sub.s $f0, $f0, $f26'),
    (' ', 'lbu $v0, %lo(active)($v0)', 'lbu $v0, %lo(active)($v0)'),
    ('r', 'lwc1 $f26, 0x48($s1)', 'lwc1 $f2, 0x48($s1)'),
    (' ', 'bnel $v0, $zero, 0x28', 'bnel $v0, $zero, 0x28'),
    ('r', 'add.s $f26, $f26, $f26', 'add.s $f2, $f2, $f2'),
    (' ', 'lui $at, %hi(balance)', 'lui $at, %hi(balance)'),
    (' ', 'lwc1 $f0, %lo(balance)($at)', 'lwc1 $f0, %lo(balance)($at)'),
    ('r', 'sub.s $f0, $f0, $f26', 'sub.s $f0, $f0, $f2'),
]


def test_reuses_the_proven_field_register_for_the_later_subtract():
    [(family, changed)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 'saved *= 2.0f;' in changed and changed.count('balance -= saved;') == 2


def test_requires_prior_agreement_and_exact_field_flag_and_global():
    assert not variants(SOURCE, 'adjust', ROWS[4:])
    assert not variants(SOURCE.replace('active != 0', 'enabled != 0'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('balance -= value;', 'total -= value;'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('0x48', '0x4C', 1), 'adjust', ROWS)


def test_does_not_replace_live_values():
    for code in (
        SOURCE.replace('balance -= value;', 'balance -= value;\n    report(saved);'),
        SOURCE.replace('balance -= value;', 'balance -= value;\n    report(value);'),
        SOURCE.replace('balance -= saved;', 'balance -= saved;\n    keep(&saved);'),
    ):
        assert not variants(code, 'adjust', ROWS)
