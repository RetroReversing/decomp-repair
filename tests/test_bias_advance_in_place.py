"""A word local read as `v + K` from some point on, advanced in place there."""
from decomprepair import bias_advance_in_place as repair

SOURCE = """
#define RECT(p, x0, x1) emit((p), (x0), (x1))
void draw(void) {
    u16 i;

    for (i = 0; i < 4; i++) {
        u32 filled;
        u16 rest;

        filled = table[i] >> 1;
        RECT(next++, 60, filled + 60);
        rest = 50 - filled;
        if (rest != 0) {
            RECT(next++, filled + 60, rest + filled + 60);
        }
    }
}
"""

ADVANCED = """        rest = 50 - filled;
        filled += 60;
        if (rest != 0) {
            RECT(next++, filled, rest + filled);
        }
"""

EARLY = SOURCE.replace("""        RECT(next++, 60, filled + 60);
        rest = 50 - filled;
""", """        rest = 50 - filled;
        RECT(next++, 60, filled + 60);
""")


def children(source, family):
    return [child for kind, child in repair.variants(source, 'draw') if kind == family]


def test_advances_after_the_last_read_of_the_old_value():
    expected = SOURCE.replace("""        rest = 50 - filled;
        if (rest != 0) {
            RECT(next++, filled + 60, rest + filled + 60);
        }
""", ADVANCED)
    assert expected in children(SOURCE, repair.FAMILY)


def test_moves_the_early_computation_past_the_next_statement_and_advances():
    expected = SOURCE.replace("""        rest = 50 - filled;
        if (rest != 0) {
            RECT(next++, filled + 60, rest + filled + 60);
        }
""", ADVANCED)
    assert expected in children(EARLY, repair.PAST_USE)


def test_narrow_locals_and_second_writes_decline():
    assert repair.variants(SOURCE.replace('u32 filled;', 'u16 filled;'), 'draw') == []
    assert repair.variants(SOURCE.replace('if (rest != 0) {', 'filled = rest;\n        if (rest != 0) {'), 'draw') == []


def test_a_sum_that_is_not_a_term_of_its_own_stays():
    source = SOURCE.replace('filled + 60, rest + filled + 60', 'rest - filled + 60, filled + 60 * rest')
    assert not any('filled += 60' in child for _, child in repair.variants(source, 'draw'))


def test_declares_itself():
    assert repair.REPAIR['families'] == repair.FAMILIES
