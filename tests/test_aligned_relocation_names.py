import pytest

from decomprepair.aligned_relocation_names import replacement

SOURCE = """extern int old;
extern void stale(void);
int update(void) { /* old */ stale(); return old; }"""
HI = ('i', 'lui $v0, %hi(goal)', 'lui $v0, %hi(?old)')
LO = ('i', 'lw $v0, %lo(goal)($v0)', 'lw $v0, %lo(?old)($v0)')
CALL = ('i', 'jal helper', 'jal ?stale')


def test_replaces_candidate_names_without_touching_comments():
    assert replacement(SOURCE, [HI, LO, CALL], {'old', 'stale'}) == (
        'extern int goal;\nextern void helper(void);\n'
        'int update(void) { /* old */ helper(); return goal; }'
    )


@pytest.mark.parametrize('rows', [
    [HI, CALL],
    [HI, LO, CALL, ('i', 'lw $v0, %lo(other)($v0)', LO[2])],
    [HI, ('i', 'lw $v0, %lo(goal)($a0)', LO[2]), CALL],
    [HI, ('i', 'lw $v0, %lo(goal+0x4)($v0)', LO[2]), CALL],
    [HI, LO, ('i', 'j helper', CALL[2])],
    [HI, LO, CALL, ('>', '', CALL[2])],
])
def test_incomplete_or_conflicting_alignment_is_rejected(rows):
    assert replacement(SOURCE, rows, {'old', 'stale'}) is None


def test_does_not_rewrite_shared_declarations():
    assert replacement(SOURCE, [HI, LO, CALL], {'old', 'stale'}, 'extern int old;') is None
