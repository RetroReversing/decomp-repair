"""Two adjacent word stores of one constant at K and K + 4 (K a multiple of 8) as one `s64` store."""
import pytest

from decomprepair import registry
from decomprepair.word_pair_doubleword_store import FAMILY, variants

DRAFT = '''extern u8 D_800BD2B8[];
void f(void) {
    func_80065A08(&D_800BD2B0);
    M2C_FIELD(D_800BD2B8, s32 *, 0) = 0;
    M2C_FIELD(D_800BD2B8, s32 *, 4) = 0;
    func_80065AD8(D_800BD2B8 - 8);
}
'''
SPLIT = 'move $v0, $zero\nmove $v1, $zero\nsw $v0, ($a0)\nsw $v1, 4($a0)\n'
ZERO = 'sw $zero, ($a0)\nsw $zero, 4($a0)\n'


def _kids(text, asm=None):
    return [s for fam, s in variants(text, 'f', asm) if fam == FAMILY]


def test_two_zero_words_become_one_doubleword():
    want = DRAFT.replace('M2C_FIELD(D_800BD2B8, s32 *, 0) = 0;\n    M2C_FIELD(D_800BD2B8, s32 *, 4) = 0;',
                         '*(s64 *)D_800BD2B8 = 0;')
    assert _kids(DRAFT) == [want]
    assert _kids(DRAFT, SPLIT) == [want]


def test_the_targets_assembly_must_show_a_split_pair():
    assert _kids(DRAFT, ZERO) == []


def test_other_spellings_offsets_and_constants():
    text = ('void f(s32 *p, u8 *q) { *(s32 *)(q + 8) = 0; *(s32 *)(q + 12) = 0; '
            '((s32 *)p)[2] = 5; ((s32 *)p)[3] = 5; *(s32 *)q = 0; *(s32 *)(q + 4) = 0; }\n')
    kids = _kids(text)
    assert any('M2C_FIELD(q, s64 *, 8) = 0;' in k for k in kids)
    assert any('M2C_FIELD(p, s64 *, 8) = 0x0000000500000005;' in k for k in kids)
    assert any('*(s64 *)q = 0;' in k for k in kids)
    assert any('M2C_FIELD(q, s64 *, 8) = 0;' in k and '*(s64 *)q = 0;' in k for k in kids)   # every pair together
    assert len(kids) <= 6


@pytest.mark.parametrize('text', [
    'void f(u8 *p) { M2C_FIELD(p, s32 *, 4) = 0; M2C_FIELD(p, s32 *, 8) = 0; }',      # K not a multiple of 8
    'void f(u8 *p) { M2C_FIELD(p, s32 *, 0) = 0; M2C_FIELD(p, s32 *, 4) = 1; }',      # different constants
    'void f(u8 *p, u8 *q) { M2C_FIELD(p, s32 *, 0) = 0; M2C_FIELD(q, s32 *, 4) = 0; }',  # different bases
    'void f(u8 *p) { M2C_FIELD(p, s32 *, 0) = 0; g(); M2C_FIELD(p, s32 *, 4) = 0; }',  # not adjacent
    'void f(u8 *p) { M2C_FIELD(p, s16 *, 0) = 0; M2C_FIELD(p, s16 *, 4) = 0; }',      # halfwords
    'void f(u8 *p) { M2C_FIELD(p, s32 *, 0) = -1; M2C_FIELD(p, s32 *, 4) = -1; }',    # a negative constant
])
def test_shapes_it_must_leave_alone(text):
    assert _kids(text) == []


def test_it_is_declared_for_the_registry():
    ours = [r for r in registry.declared() if FAMILY in r.families]
    assert len(ours) == 1 and registry.problems(ours[0]) == []
