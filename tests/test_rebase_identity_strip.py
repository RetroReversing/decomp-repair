from decomprepair.rebase_identity_strip import FAMILY, variants

HELPERS = """typedef struct { u8 type; u8 pad[0x13]; s32 count; } Scene;
extern Scene gScene;
extern s32 gTotal;
inline static u8 *rebase(u8 *arg0, Scene *arg1)
{
  return ((u8 *) (&gScene)) + (arg0 - ((u8 *) arg1));
}

inline static Scene *base()
{
  return &gScene;
}

inline static volatile s32 rd(volatile s32 *arg0)
{
  return *arg0;
}
"""

SOURCE = HELPERS + """
void f(void)
{
  s16 i = 0;
  do
  {
    i++;
  }
  while (rd((volatile s32 *) rebase((u8 *) (&gTotal), base())) > ((s16) i));
}
"""


def test_the_identity_detour_is_written_as_the_pointer():
    [(family, text)] = variants(SOURCE, 'f')
    assert family == FAMILY
    assert 'rd((volatile s32 *) ((u8 *) (&gTotal))) > ((s16) i)' in text
    assert 'rebase((u8 *)' not in text.split('void f(void)')[1]
    assert text.count('inline static u8 *rebase') == 1  # the helpers stay


def test_a_pointer_rebased_onto_another_symbol_is_left_alone():
    other = SOURCE.replace('return ((u8 *) (&gScene))', 'return ((u8 *) (&gTotal))')
    assert variants(other, 'f') == []


def test_a_base_that_is_not_the_symbol_is_left_alone():
    other = SOURCE.replace('return &gScene;', 'return &gOther;')
    assert variants(other, 'f') == []


def test_a_direct_address_argument_is_recognised_too():
    text = SOURCE.replace('base()', '&gScene')
    [(_, out)] = variants(text, 'f')
    assert 'rd((volatile s32 *) ((u8 *) (&gTotal)))' in out


def test_nothing_without_the_helpers():
    assert variants('void f(void)\n{\n    g();\n}\n', 'f') == []
