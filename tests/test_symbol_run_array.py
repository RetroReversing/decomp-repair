"""Scalars that sit inside a block the function clears, written as the elements of that block's array."""
from decomprepair import registry
from decomprepair.symbol_run_array import FAMILY, variants

SOURCE = '''extern s32 D_80112E98;
extern s32 D_80112E9C;
extern s32 D_80112EA0;
extern s32 D_80112EB0;
extern s32 D_80120000;
void pick(s32 a, s32 b)
{
  memset(&D_80112E98, 0, 0x24);
  if (a)
  {
    D_80112E9C = 1;
    D_80112EA0 = 1;
  }
  else if (b)
  {
    *((s32 *) (((char *) (&D_80112EB0)) + 0)) = 1;
    *((s32 *)((char *)&D_80112EB0 - 0x10)) = 1;
    *((s32 *) (((char *) (&D_80112EB0)) + 4)) = 1;
    *((s32 *)((char *)&D_80112EB0 - 8)) = 1;
  }
  D_80120000 = 2;
}
'''


def test_the_scalars_and_casts_inside_the_cleared_block_become_its_elements():
    # a 417-instruction input handler: the hoisted address registers were the target's only with one symbol (4236 -> 3145)
    (family, text), = variants(SOURCE, 'pick')
    assert family == FAMILY
    assert 'extern s32 D_80112E98[];' in text and 'memset(D_80112E98, 0, 0x24);' in text
    for k, want in ((1, 'D_80112E98[1] = 1;'), (2, 'D_80112E98[2] = 1;'), (6, 'D_80112E98[6] = 1;'), (7, 'D_80112E98[7] = 1;'),
                    (4, 'D_80112E98[4] = 1;')):
        assert want in text
    assert text.count('D_80112E98[2] = 1;') == 2  # the symbol and the cast of the same word
    assert 'D_80112E9C = 1' not in text and '(char *)' not in text
    assert 'D_80120000 = 2;' in text  # outside the block: untouched


def test_an_address_outside_the_cleared_block_or_not_a_word_is_left_alone():
    (_, shorter), = variants(SOURCE.replace('0x24', '0x10'), 'pick')   # the block ends before EB0: its forms stay as they are
    assert '*((s32 *) (((char *) (&D_80112EB0)) + 0)) = 1;' in shorter and 'D_80112E98[2] = 1;' in shorter
    assert variants(SOURCE.replace('0x24', '0x8'), 'pick') == []   # one word inside: nothing to unify
    (_, halfword), = variants(SOURCE.replace('extern s32 D_80112E9C;', 'extern s16 D_80112E9C;'), 'pick')   # a halfword is no element
    assert '    D_80112E9C = 1;\n' in halfword and 'D_80112E98[2] = 1;' in halfword
    assert variants(SOURCE.replace('memset(&D_80112E98, 0, 0x24)', 'memset(&D_80112E98, 1, 0x24)'), 'pick') == []
    assert variants(SOURCE.replace('extern s32 D_80112E98;\n', ''), 'pick') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'symbol_run_array' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'symbol_run_array':
            assert registry.problems(repair) == []
