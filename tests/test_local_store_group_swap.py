"""Two neighbouring groups of stores to two different locals written in the other order, as whole groups."""
from decomprepair.local_store_group_swap import FAMILY, variants

# A bounding-box pass (SN64 GCC 2.8.1): two local arrays filled with their sentinels, three stores each.
BOUNDS = '''void f(Vtx *v, s32 n, Box *out)
{
    s32 min[3];
    s32 max[3];
    s32 i;
    max[0] = 0x80000001;
    max[1] = 0x80000001;
    max[2] = 0x80000001;
    min[0] = 0x7FFFFFFF;
    min[1] = 0x7FFFFFFF;
    min[2] = 0x7FFFFFFF;
    for (i = 0; i < n; i++) {
        if (v[i].x < min[0]) {
            min[0] = v[i].x;
        }
        if (max[0] < v[i].x) {
            max[0] = v[i].x;
        }
    }
    out->min = min[0];
    out->max = max[0];
}
'''

SWAPPED = '''    min[0] = 0x7FFFFFFF;
    min[1] = 0x7FFFFFFF;
    min[2] = 0x7FFFFFFF;
    max[0] = 0x80000001;
    max[1] = 0x80000001;
    max[2] = 0x80000001;
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_two_sentinel_groups_swap():
    kids = _children(BOUNDS)
    assert len(kids) == 1 and SWAPPED in kids[0]
    original = SWAPPED[SWAPPED.index('    max'):] + SWAPPED[:SWAPPED.index('    max')]
    assert kids[0] == BOUNDS.replace(original, SWAPPED)


def test_a_group_that_reads_the_other_stays():
    assert _children(BOUNDS.replace('    min[2] = 0x7FFFFFFF;', '    min[2] = max[1];')) == []


def test_an_array_that_decays_or_is_address_taken_stays():
    assert _children(BOUNDS.replace('    out->max = max[0];', '    out->max = max[0];\n    g(max);')) == []
    assert _children(BOUNDS.replace('    s32 i;\n', '    s32 i;\n    s32 *p = &min[1];\n')) == []


def test_globals_and_pointers_are_not_swapped():
    text = BOUNDS.replace('    s32 min[3];\n', '').replace('    s32 max[3];\n', '    s32 *max;\n')
    assert _children(text) == []


def test_two_single_stores_are_left_to_other_families():
    text = BOUNDS.replace('    max[1] = 0x80000001;\n    max[2] = 0x80000001;\n', '').replace('    min[1] = 0x7FFFFFFF;\n    min[2] = 0x7FFFFFFF;\n', '')
    assert _children(text) == []
