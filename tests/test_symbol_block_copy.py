"""m2c's word-by-word copies from one symbol, as the struct assignment they were."""
from decomprepair import registry
from decomprepair import symbol_block_copy as block

SOURCE = '''extern s32 D_80000000;
extern s32 D_80000004;
void boot(void)
{
    D_80000000 = M2C_FIELD(&handler, s32 *, 0);
    D_80000004 = M2C_FIELD(&handler, s32 *, 4);
    M2C_FIELD((void *)0x80000080, s32 *, 0) = (s32) M2C_FIELD(&handler, s32 *, 0);
    M2C_FIELD((void *)0x80000080, s32 *, 4) = (s32) M2C_FIELD(&handler, s32 *, 4);
    run();
}
'''


def children(source=SOURCE):
    found = block.variants(source, 'boot')
    assert all(family == block.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_every_run_becomes_an_assignment_in_one_child_per_spelling():
    constant, symbol = children()
    assert '    *(__repair_block2 *) 0x80000000 = *(__repair_block2 *) &handler;\n' in constant
    assert '    *(__repair_block2 *) (void *)0x80000080 = *(__repair_block2 *) &handler;\n' in constant
    assert '    *(__repair_block2 *) &D_80000000 = *(__repair_block2 *) &handler;\n' in symbol
    assert constant.index('typedef struct { s32 w[2]; } __repair_block2;') < constant.index('void boot(')
    assert 'M2C_FIELD' not in constant


def test_words_that_are_not_consecutive_are_left_alone():
    assert children(SOURCE.replace('&handler, s32 *, 4)', '&handler, s32 *, 8)')) == []


def test_the_family_is_registered():
    assert any(block.FAMILY in repair.families for repair in registry.declared())
