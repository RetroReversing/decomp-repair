"""One plain assignment moved through a run of independent ones (a 2,503-instruction update, 2797 -> 2287)."""
from decomprepair.assignment_run_move import FAMILY, variants

SOURCE = """void hit(void)
{
    if (d < best) {
        best = d;
        kind = 1;
        target = gTarget;
        *(Vec3 *)&local.sp30 = *(Vec3 *)&local.sp40;
        saved = gPlayer;
    }
}
"""


def children(source=SOURCE):
    found = variants(source, 'hit')
    assert all(family == FAMILY for family, _ in found)
    return [text for _, text in found]


def test_a_statement_moves_through_the_run():
    found = children()
    assert any('        kind = 1;\n        best = d;\n' in t for t in found)
    assert any('        saved = gPlayer;\n        *(Vec3 *)&local.sp30' in t for t in found)
    assert len(found) == len(set(found))


def test_a_dependent_statement_does_not_pass_what_it_reads():
    source = SOURCE.replace('kind = 1;', 'kind = best;')
    assert not any(t.index('kind = best;') < t.index('best = d;') for t in children(source))


def test_a_frame_store_does_not_pass_a_frame_read():
    source = SOURCE.replace('saved = gPlayer;', 'saved = local.sp30;')
    assert not any(t.index('saved = local.sp30;') < t.index('*(Vec3 *)&local.sp30') for t in children(source))


def test_calls_end_the_run():
    source = SOURCE.replace('target = gTarget;', 'target = pick();')
    assert children(source) == []
