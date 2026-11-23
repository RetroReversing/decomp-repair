"""chained_identical_arm_flip: an identity `else if` collapsed, with the branch's polarity swapped as the second child.

Synthetic shape of a 118-instruction KMC menu function (280 -> 60 with the flip; the collapse alone is neutral)."""
from decomprepair import chained_identical_arm_flip as s

SOURCE = '''extern u32 gFlags;
extern u32 gTable[];
inline static int same(void) { return !gTable; }

void pick(u32 **out) {
    u32 *color;
    if (!(gFlags & 1)) {
        color = gTable + 9;
    } else if (same()) {
        color = gTable + 1;
    } else {
        color = gTable + 1;
    }
    *out = color;
}
'''


def _found(source=SOURCE):
    return dict(s.variants(source, 'pick'))


def test_the_identical_arms_are_written_once():
    text = _found()[s.COLLAPSE_FAMILY]
    assert 'same()' not in text.split('void pick')[1]
    assert 'if (!(gFlags & 1))' in text and text.count('gTable + 1') == 1


def test_the_flip_removes_the_negation_and_swaps_the_arms():
    text = _found()[s.FAMILY].split('void pick')[1]
    assert 'if (gFlags & 1)' in text and text.index('gTable + 1') < text.index('gTable + 9')


def test_a_plain_condition_is_negated_with_a_not():
    text = _found(SOURCE.replace('!(gFlags & 1)', 'gFlags'))[s.FAMILY]
    assert 'if (!(gFlags))' in text


def test_differing_arms_and_loops_decline():
    assert s.variants(SOURCE.replace('gTable + 1;\n    } else {', 'gTable + 2;\n    } else {', 1), 'pick') == []
    assert s.variants(SOURCE.replace('    *out = color;', '    while (*out) { *out = color; }'), 'pick') == []


def test_the_module_declares_itself_for_the_registry():
    assert s.REPAIR['variants'] is s.variants and s.REPAIR['families'] == s.FAMILIES
