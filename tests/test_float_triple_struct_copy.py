"""Three float member copies in a row written as one struct assignment (a 2,503-instruction update, 19868 -> 14293)."""
from decomprepair.float_triple_struct_copy import FAMILY, RECORD, variants

SOURCE = """void update(void *arg0)
{
    struct { f32 sp30; f32 sp34; f32 sp38; f32 sp40; f32 sp44; f32 sp48; f32 hit50[3]; } local;
    void *obj;

    (*(f32 *)((char *)(obj) + 0xEC)) = local.sp40;
    (*(f32 *)((char *)(obj) + 0xF0)) = local.sp44;
    (*(f32 *)((char *)(obj) + 0xF4)) = local.sp48;
    local.hit50[0] = (*(f32 *)((char *)(arg0) + 0x3C));
    local.hit50[1] = (f32) (*(f32 *)((char *)(arg0) + 0x40));
    local.hit50[2] = (*(f32 *)((char *)(arg0) + 0x44));
    local.sp30 = local.sp40;
    local.sp34 = local.sp44;
    local.sp38 = local.sp48;
    use(&local);
}
"""

MEMBER_OUT = f'    *({RECORD} *)((char *)(obj) + 0xEC) = *({RECORD} *)&local.sp40;'
MEMBER_IN = f'    *({RECORD} *)&local.hit50[0] = *({RECORD} *)((char *)(arg0) + 0x3C);'
FRAME = f'    *({RECORD} *)&local.sp30 = *({RECORD} *)&local.sp40;'


def children(source=SOURCE):
    found = variants(source, 'update')
    assert all(family == FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_member_copies_come_together_in_one_child_with_the_record_declared():
    found = children()
    together = [t for t in found if MEMBER_OUT in t and MEMBER_IN in t and FRAME not in t]
    assert len(together) == 1
    text = together[0]
    assert text.index(f'typedef struct {{ f32 x, y, z; }} {RECORD};') < text.index('void update(')
    assert '0xF0' not in text and 'hit50[1]' not in text
    assert '    local.sp34 = local.sp44;' in text


def test_every_copy_at_once_and_each_alone_are_offered():
    found = children()
    assert any(MEMBER_OUT in t and MEMBER_IN in t and FRAME in t for t in found)
    alone = [t for t in found if sum(line in t for line in (MEMBER_OUT, MEMBER_IN, FRAME)) == 1]
    assert len(alone) == 3  # the frame copy alone is also the frame-only set: offered once
    assert len(found) == len(set(found))


def test_cells_that_are_not_consecutive_are_left_alone():
    source = SOURCE.replace('+ 0xF4)) = local.sp48', '+ 0xF8)) = local.sp48')
    source = source.replace('local.hit50[2] =', 'local.sp48 =').replace('local.sp38 = local.sp48;', 'local.sp3C = local.sp48;')
    assert children(source) == []


def test_the_record_is_not_declared_twice():
    source = f'typedef struct {{ f32 x, y, z; }} {RECORD};\n' + SOURCE
    assert all(t.count(f'}} {RECORD};') == 1 for t in children(source))
