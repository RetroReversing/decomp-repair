from decomprepair.zero_index_member import FAMILY, variants

SOURCE = '''extern PadS D_801E9990[];
extern s32 D_801E99C0;
extern s32 D_801E99C4;
extern u8 D_80300000;
void func_80000000(u16 arg0)
{
    u16 player;
    player = 0;
    if (D_801E9990[player].v == 1) { step(player); }
    if (D_801E99C0 == 1 && D_801E99C4 != 0) { D_80300000 = 1; }
}
'''


def test_scalars_in_the_first_record_read_through_the_zero_index():
    found = variants(SOURCE, 'func_80000000')
    assert [family for family, _ in found] == [FAMILY] * 3
    both = found[0][1]
    assert 'if ((*(s32 *) ((char *) &D_801E9990[player] + 0x30)) == 1 &&' in both
    assert '(*(s32 *) ((char *) &D_801E9990[player] + 0x34)) != 0' in both
    assert 'extern s32 D_801E99C0;' in both and 'D_80300000 = 1;' in both


def test_a_local_that_changes_is_not_an_index_of_zero():
    assert not variants(SOURCE.replace('step(player);', 'player++;'), 'func_80000000')
    assert not variants(SOURCE.replace('player = 0;', 'player = arg0;'), 'func_80000000')
    assert not variants(SOURCE.replace('step(player);', 'fill(&player);'), 'func_80000000')


def test_declarations_may_come_from_the_header():
    header = 'extern s32 D_801E99C0;\n'
    source = SOURCE.replace('extern s32 D_801E99C0;\n', '').replace('extern s32 D_801E99C4;\n', '')
    assert len(variants(source, 'func_80000000', header)) == 1
