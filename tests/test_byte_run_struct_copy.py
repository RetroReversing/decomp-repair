"""m2c's byte-by-byte load of a small record, written back as one record copy."""
from decomprepair import byte_run_struct_copy as c
from decomprepair import registry

SOURCE = '''extern s32 gBlock;
void f(void)
{
  s8 sp20;
  s8 sp21;
  s8 sp22;
  s32 *q;
  s32 y;
  void *temp_v0;

  temp_v0 = &gBlock + 0x40;
  sp20 = (*(s8 *)((char *)(&gBlock) + 0x40));
  q = &gTable + 0x1;
  sp21 = (*(s8 *)((char *)(temp_v0) + 1));
  sp22 = (*(s8 *)((char *)(temp_v0) + 2));
  g(q, y, &sp20);
  y = sp21;
}
'''


def test_one_copy():
    (family, text), = c.variants(SOURCE, 'f')
    assert family == 'byte_run_struct_copy'
    assert '  struct { s8 b[3]; } sp20;\n  s32 *q;' in text
    assert '  sp20 = *(__typeof__(sp20) *) ((char *)(&gBlock) + 0x40);\n  q = &gTable + 0x1;\n  g(q, y, sp20.b);' in text
    assert 'y = sp20.b[1];' in text
    assert 'temp_v0' not in text and 'sp21' not in text and 'sp22' not in text


def test_m2c_field_reads():
    source = SOURCE.replace('(*(s8 *)((char *)(temp_v0) + 1))', 'M2C_FIELD(temp_v0, s8 *, 1)').replace(
        '(*(s8 *)((char *)(temp_v0) + 2))', 'M2C_FIELD(temp_v0, s8 *, 2)')
    (_, text), = c.variants(source, 'f')
    assert 'sp22' not in text and 'struct { s8 b[3]; } sp20;' in text


def test_left_alone_otherwise():
    # bytes from somewhere else, a read that is not behind the same address, a call or store between the reads
    assert c.variants(SOURCE.replace('(temp_v0) + 1', '(other) + 1').replace('(temp_v0) + 2', '(other) + 2'), 'f') == []
    assert c.variants(SOURCE.replace('(temp_v0) + 1', '(temp_v0) + 5'), 'f') == []
    assert c.variants(SOURCE.replace('q = &gTable + 0x1;', 'h();'), 'f') == []
    assert c.variants(SOURCE.replace('q = &gTable + 0x1;', 'gTable = 0, q = 0;').replace(', q = 0', ';\n  *q = 0'), 'f') == []
    # a byte assigned again is no initialiser
    assert c.variants(SOURCE.replace('  y = sp21;', '  sp20 = 0;'), 'f') == []


def test_registered():
    assert registry.get('byte_run_struct_copy') is not None
