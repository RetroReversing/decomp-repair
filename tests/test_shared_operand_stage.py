import re

from decomprepair import shared_operand_stage
from decomprepair.shared_operand_stage import FAMILY, variants

SOURCE = """void build(void *rec, s32 wide) {
    s32 count;
    s32 bytes;
    u8 flags;

    if (wide != 0) {
        count = 4;
        bytes = (*((u16 *) (((char *) rec) + 0x40))) * 6;
        flags = (*((u8 *) (((char *) rec) + 0x48))) | 4;
    } else {
        count = 3;
        bytes = (*((u16 *) (((char *) rec) + 0x40))) * 3;
        flags = (*((u8 *) (((char *) rec) + 0x48))) | 8;
    }
    *((u8 *) (((char *) rec) + 0x48)) = flags;
    alloc(bytes, count);
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_every_statement_of_a_load_type_goes_through_one_shared_local():
    children = variants(SOURCE, 'build')
    assert [family for family, _ in children] == [FAMILY, FAMILY]
    texts = [_flat(text) for _, text in children]
    both = next(t for t in texts if '__repair_stage_u16' in t)
    assert 's32 __repair_stage_u16;' in both
    assert '__repair_stage_u16 = (*((u16 *) (((char *) rec) + 0x40))); bytes = __repair_stage_u16 * 6;' in both
    assert '__repair_stage_u16 = (*((u16 *) (((char *) rec) + 0x40))); bytes = __repair_stage_u16 * 3;' in both
    # the byte reads are the other child's, the u16 ones untouched there
    other = next(t for t in texts if '__repair_stage_u8' in t)
    assert 's32 __repair_stage_u8;' in other and '__repair_stage_u16' not in other
    assert 'flags = __repair_stage_u8 | 4;' in other and 'flags = __repair_stage_u8 | 8;' in other
    assert 'bytes = (*((u16 *) (((char *) rec) + 0x40))) * 6;' in other


def test_a_child_differs_from_the_source_only_by_the_staging():
    for _, text in variants(SOURCE, 'build'):
        unstaged = re.sub(r'\n  s32 __repair_stage_\w+;', '', text)
        unstaged = re.sub(r'__repair_stage_\w+ = (\(\*[^;]*\));\s*(\w+) = __repair_stage_\w+ ', r'\2 = \1 ', unstaged)
        assert _flat(unstaged) == _flat(SOURCE)


def test_nothing_for_one_statement_a_wide_load_or_a_name_already_staged():
    one = SOURCE.replace('bytes = (*((u16 *) (((char *) rec) + 0x40))) * 3;', 'bytes = 3;')
    assert [t for _, t in variants(one, 'build') if '__repair_stage_u16' in t] == []
    wide = SOURCE.replace('(u16 *)', '(u32 *)').replace('(*((u32 *) (((char *) rec) + 0x40)))', '(*((f64 *) (((char *) rec) + 0x40)))')
    assert not any('__repair_stage_f64' in t for _, t in variants(wide, 'build'))
    first = variants(SOURCE, 'build')[0][1]
    assert not [t for _, t in variants(first, 'build') if '__repair_stage_u16' in t and t.count('s32 __repair_stage_u16;') > 1]
    assert variants('void f(void *p) { int x; x = (*((u16 *) (((char *) p) + 4))) * 2; }', 'f') == []


def test_the_family_is_registered():
    from decomprepair import registry
    assert any(entry.module.endswith('shared_operand_stage') for entry in registry.declared())
    assert shared_operand_stage.REPAIR['needs'] == ('source', 'name')
