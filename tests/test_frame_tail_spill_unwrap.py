"""The last scalar members of a frame struct as plain spilled locals (a 2,503-instruction update, 6151 -> 5435)."""
from decomprepair.frame_tail_spill_unwrap import FAMILY, variants

SOURCE = """void update(void *arg0)
{
    struct {
        f32 sp30;
        u8 pad34[12];
        void *sp40;
        u8 pad44[4];
        s32 sp48;
    } local;
    s32 i;

    local.sp40 = arg0;
    local.sp48 = 3;
    use(&local.sp30, local.sp40, local.sp48);
}
"""


def children(source=SOURCE):
    found = variants(source, 'update')
    assert all(family == FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_trailing_scalars_leave_the_struct_with_the_padding_shortened():
    found = children()
    both = [t for t in found if '    void *sp40;\n    s32 sp48;\n    s32 i;' in t]
    assert len(both) == 3
    assert any('u8 pad34[4];' in t for t in both) and any('u8 pad34[8];' in t for t in both)
    text = both[0]
    assert '        u8 pad34[12];\n    } local;\n' in text
    assert 'pad44' not in text
    assert 'use(&local.sp30, sp40, sp48);' in text and 'local.sp40' not in text


def test_a_member_whose_address_is_taken_stays():
    source = SOURCE.replace('use(&local.sp30,', 'use(&local.sp40,')
    found = children(source)
    assert found and all('void *sp40;' not in t.split('} local;')[1] for t in found)
    assert all('local.sp40' in t for t in found)


def test_a_name_already_in_use_is_not_taken():
    assert children(SOURCE.replace('    s32 i;', '    s32 sp48;')) == []
