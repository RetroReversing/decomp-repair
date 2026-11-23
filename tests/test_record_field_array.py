"""Parallel `D_XXXXXXXX` tables read through one stepped byte offset, written as an array of records."""
from decomprepair import record_field_array as t

SOURCE = '''extern s16 D_800C7E10;
extern s16 D_800C7E12;
extern s32 D_800C7E14;
extern u16 D_800C7E18;
void f(void *s)
{
  u32 i;
  register s32 off;
  for (i = 0, off = 0; i < 4U; i++)
  {
    if (g(i))
    {
      h(*((s16 *) (((char *) (&D_800C7E10)) + off)), *((s16 *) (((char *) (&D_800C7E12)) + off)), (s32) (*((u16 *) (((char *) (&D_800C7E18)) + off))), *((s32 *) (((char *) (&D_800C7E14)) + off)));
    }
    off += 0xC;
  }
}
'''


def test_the_fields_become_one_record_array_indexed_by_the_counter():
    # A 1133-instruction effect spawner, KMC GCC 2.7.2: 185 -> 125, the reduced `i * 12` register initialised after
    # the loop's hoisted constants as in the target (the user offset's `move $s0, $zero` came before them).
    out = t.variants(SOURCE, 'f')
    assert len(out) == 1
    child = out[0][1]
    assert 'typedef struct { s16 x_0; s16 x_2; s32 x_4; u16 x_8; char pad_A[2]; } Rec_D_800C7E10;' in child
    assert 'extern Rec_D_800C7E10 D_800C7E10[];' in child and 'extern s16 D_800C7E10;' not in child
    assert 'for (i = 0; i < 4U; i++)' in child and 'off += 0xC;' not in child
    assert ('h(D_800C7E10[i].x_0, D_800C7E10[i].x_2, (s32) (D_800C7E10[i].x_8), D_800C7E10[i].x_4);') in child


def test_left_alone_when_the_offset_is_read_elsewhere_or_the_fields_do_not_fit():
    other = SOURCE.replace('    off += 0xC;\n', '    off += 0xC;\n    k(off);\n')
    assert t.variants(other, 'f') == []
    small = SOURCE.replace('off += 0xC;', 'off += 0x8;')
    assert t.variants(small, 'f') == []  # D_800C7E18 lies 8 bytes past the base: no 8-byte record holds it
    named = SOURCE.replace('    if (g(i))', '    D_800C7E10 = 1;\n    if (g(i))')
    assert t.variants(named, 'f') == []
    in_header = t.variants(SOURCE, 'f', header='extern s16 D_800C7E10;')
    assert in_header == []


def test_a_do_while_counter_and_an_offset_statement():
    loop = SOURCE.replace('  for (i = 0, off = 0; i < 4U; i++)\n  {', '  i = 0;\n  off = 0;\n  do\n  {').replace(
        '    off += 0xC;\n  }\n}', '    off += 0xC;\n    i += 1;\n  }\n  while (i < 4U);\n}')
    out = t.variants(loop, 'f')
    assert len(out) == 1 and '  off = 0;\n' not in out[0][1] and 'D_800C7E10[i].x_4' in out[0][1]


def test_it_declares_itself():
    from decomprepair import registry
    assert any(r.module == 'record_field_array' for r in registry.declared())
