"""`if ((a && b) || c)` written as its branches, so `a && b` is not merged into a range test (1786 -> 0)."""
from decomprepair.compound_or_goto_ladder import FAMILY, variants

SOURCE = """void turn(Obj *self, s16 diff, s16 rate)
{
    if (diff > 0) {
        self->rot += rate;
    } else if ((diff < 0 && diff >= -0x7FF) || (diff > 0x800)) {
        self->rot -= rate;
    }
    self->done = 1;
}
"""


def test_the_condition_becomes_branches():
    [(family, child)] = variants(SOURCE, 'turn')
    assert family == FAMILY
    flat = ' '.join(child.split())
    assert ('else { if (diff < 0) { if (diff >= -0x7FF) { goto ladder_body_2; } } '
            'if (diff <= 0x800) { goto ladder_done_2; } ladder_body_2: { self->rot -= rate; } ladder_done_2:; }') in flat
    assert flat.endswith('self->done = 1; }')


def test_other_conditions_are_negated_whole():
    child = variants(SOURCE.replace('(diff > 0x800)', 'self->hit'), 'turn')[0][1]
    assert 'if (!(self->hit)) {' in child


def test_left_alone():
    assert not variants(SOURCE.replace('        self->rot -= rate;\n    }',
                                       '        self->rot -= rate;\n    } else {\n        self->rot = 0;\n    }'), 'turn')
    assert not variants(SOURCE.replace('diff < 0 && diff >= -0x7FF', 'diff < 0'), 'turn')
    assert not variants(SOURCE.replace('self->rot -= rate;', 'here: self->rot -= rate;'), 'turn')
