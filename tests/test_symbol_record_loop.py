from decomprepair.symbol_record_loop import DIFFERENCE, FAMILY, variants

SOURCE = '''extern char D_8000A010[];
extern char D_8000A018[];
extern char D_8000A01C[];
extern char D_8000A054[];
extern char D_8000C004[];
extern char D_8000D000[];
extern char func_80001000[];

void setup(void)
{
  u32 i;
  s32 far;
  s32 off;
  s32 size;
  far = 0;
  off = 0;
  size = ((s32) (func_80001000 + 0xD0)) - ((s32) func_80001000);
  for (i = 0; i < 2; i++)
  {
    do { *((s32 *) (D_8000A054 + off)) = 0; } while (0);
    *((s32 *) (D_8000A010 + off)) = 2;
    *((s32 *) (D_8000A018 + off)) = (s32) func_80001000;
    *((s32 *) (D_8000A01C + off)) = size;
    *((s32 *) (D_8000C004 + far)) = 0;
    far += 0x184;
    off += 0x58;
  }
  if (far)
  {
    start(D_8000D000);
  }
  else
  {
    start(D_8000D000);
    if (1)
    {
    }
  }
}
'''


def test_offsets_difference_and_dead_guard_become_one_child():
    children = variants(SOURCE, 'setup')
    full = [text for family, text in children if family == FAMILY and 'func_800010D0) - ((s32) func_80001000)' in text
            and 'extern Rec_D_8000A000 D_8000A000[];' in text]
    assert full, children
    text = full[0]
    assert 'D_8000A000[i].x_54 = 0;' in text
    assert 'D_8000A000[i].x_1C = ((s32) func_800010D0) - ((s32) func_80001000);' in text
    assert 'D_8000C004[i].x_0 = 0;' in text
    assert 'extern char func_800010D0[];' in text
    body = text[text.index('void setup'):]
    assert 'off' not in body and 'far' not in body and 'size' not in body and 'do' not in body
    assert body.count('start(D_8000D000);') == 1


def test_base_at_the_lowest_symbol_and_difference_alone_are_offered():
    children = variants(SOURCE, 'setup')
    assert any('D_8000A010[i].x_0 = 2;' in text for family, text in children if family == FAMILY)
    assert any(family == DIFFERENCE and 'func_800010D0' in text and '(D_8000A054 + off)' in text
               for family, text in children)


def test_an_offset_read_after_the_loop_keeps_its_loop():
    source = SOURCE.replace('  if (far)\n', '  use(off);\n  if (far)\n')
    assert not any('[i].x_54' in text for _, text in variants(source, 'setup'))


def test_nothing_without_byte_array_symbols():
    assert variants('void f(void) { g(); }\n', 'f') == []
