import re

from decomprepair.ramp_loop_shapes import (
    ADDRESS,
    COMBINED,
    CONSTANT,
    MASK_DROP,
    NARROW,
    PRODUCT,
    RMW,
    UNMASKED,
    variants,
)

SOURCE = """extern s32 gColor;
extern void *gState;
extern void *gMenu;
void step(void)
{
  s32 prod;
  s32 alpha;
  s32 out;
  s32 i;
  void *menu;
  void *rows;
  alpha = 0;
  i = 0;
  {
    void *entry = gState;
    {
      void *loopRows = entry;
      s32 *flags = &gColor;
      do
      {
        s32 diff = *((s16 *) (((char *) entry) + 0x32));
        alpha = 0xFF;
        if (diff < 0)
        {
          prod = ((-diff) * 0x16) & 0xFFFFu;
          if (prod >= 0)
          {
            if (prod >= 0x100)
            {
              out = 0;
            }
            else
            {
              out = 0xFF - prod;
            }
          }
          else
          {
            out = 0xFF;
          }
          alpha = out;
        }
        *((s32 *) (((char *) loopRows) + 0x10)) = (s32) (((*flags) & (~0xFF)) | (alpha & 0xFFFF));
        i += 1;
      }
      while (i < 4);
    }
    *((u16 *) (((char *) gState) + 0x32)) += 6;
    do
    {
      menu = gMenu; out = 0x96;
    }
    while (0);
  }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _found(family):
    return [_flat(t) for kind, t in variants(SOURCE, 'step') if kind == family]


def test_the_product_is_unmasked_and_written_inline():
    (drop,), (inline,), (both,) = _found(MASK_DROP), _found(PRODUCT), _found(UNMASKED)
    assert 'prod = ((-diff) * 0x16);' in drop
    assert '0xFF - (((-diff) * 0x16) & 0xFFFFu)' in inline and 's32 prod;' not in inline
    assert 'if (((-diff) * 0x16) >= 0x100)' in both and 'prod' not in both


def test_a_local_every_use_masks_is_declared_narrow():
    assert any('u16 alpha;' in t and 's32 alpha;' not in t for t in _found(NARROW))


def test_a_symbol_address_local_is_written_where_it_is_read():
    (text,) = _found(ADDRESS)
    assert 'flags' not in text and '*(s32 *)((char *)&gColor)' in text


def test_a_literal_minus_gets_a_named_constant_before_the_loop_entry_copy():
    (text,) = _found(CONSTANT)
    assert text.index('s32 k0xFF = 0xFF;') < text.index('void *loopRows = entry;') and 'k0xFF - ' in text


def test_the_read_modify_write_goes_around_the_load():
    (text,) = _found(RMW)
    assert re.search(r'rmwOld = \*\(\(u16 \*\).*menu = gMenu; .*= rmwOld \+ 6; do \{ out = 0x96; \} while \(0\);', text)


def test_the_combination_applies_every_edit_and_the_chains_grow():
    combined = _found(COMBINED)
    assert len(combined) >= 3
    last = combined[-1]
    assert 'prod' not in last and 'u16 alpha;' in last and 'flags' not in last
    assert last.index('s32 k0xFF = 0xFF;') < last.index('void *loopRows') and 'rmwOld' in last


def test_a_function_with_none_of_them_has_no_variants():
    assert variants('void f(void)\n{\n  s32 a;\n  a = 1;\n}\n', 'f') == []
