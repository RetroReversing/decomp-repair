"""A scalar global stored and read back: `volatile` makes gcc load it again (a KMC gcc 2.7.2 menu function)."""
from decomprepair import scalar_reload_volatile_repairs as t

SOURCE = '''extern u16 sAction;
extern u8 sOther;
extern void *gPtr;
extern u16 sCounter[];
void f(s32 v)
{
  sAction = v;
  g(sAction, &sOther);
  sCounter[0] = 1;
  h(sCounter[0], gPtr);
}
'''


def test_a_stored_then_read_scalar_is_declared_volatile():
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert len(out) == 1
    assert 'extern volatile u16 sAction;' in out[0]
    assert 'volatile u8' not in out[0] and 'volatile void' not in out[0] and 'volatile u16 sCounter' not in out[0]


def test_each_global_alone_and_all_together():
    source = SOURCE.replace('  sCounter[0] = 1;\n  h(sCounter[0], gPtr);', '  sOther = 2;\n  h(sOther);').replace('&sOther', '0')
    out = [text for _, text in t.variants(source, 'f')]
    assert len(out) == 3
    assert out[-1].count('volatile') == 2


def test_already_volatile_unread_or_address_taken_are_left_alone():
    assert t.variants(SOURCE.replace('extern u16 sAction', 'extern volatile u16 sAction'), 'f') == []
    assert t.variants('extern u16 a;\nvoid f(void)\n{\n  g(a);\n  a = 1;\n}\n', 'f') == []
    assert t.variants('extern u16 a;\nvoid f(void)\n{\n  a = 1;\n  g(&a);\n}\n', 'f') == []
