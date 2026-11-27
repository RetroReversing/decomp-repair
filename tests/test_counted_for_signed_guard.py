"""A signed counter under a `n > 0` guard is the `for` loop's own test at zero (a directory search, 24 -> 0)."""
from decomprepair.counted_loop_shapes import for_variants

SOURCE = """void walk(Dir *dir)
{
    s32 j;

    j = 0;
    if (dir->count > 0) {
        do {
            visit(j);
            j++;
        } while (j < dir->count);
    }
}
"""


def test_a_signed_counter_under_a_positive_guard_becomes_a_for():
    [(_, text)] = for_variants(SOURCE, 'walk')
    assert 'for (j = 0; j < dir->count; j += 1) {' in text
    assert 'if (dir->count > 0)' not in text


def test_a_signed_counter_under_a_nonzero_guard_stays():
    assert for_variants(SOURCE.replace('dir->count > 0', 'dir->count != 0'), 'walk') == []


def test_the_mirrored_guard_is_the_same_test():
    assert for_variants(SOURCE.replace('dir->count > 0', '0 < dir->count'), 'walk')
