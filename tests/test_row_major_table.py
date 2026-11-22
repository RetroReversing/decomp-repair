"""row_major_table: a row-major table as `D[row][column]` where m2c walked a word and an address.

Shape of a 374-instruction KMC function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 35 or 645 -> 0): the three
accesses to two parallel tables together, the pointer form scoring 2215 when kept."""
from decomprepair import row_major_table as table

SOURCE = '''extern u8 gStart[];
extern s32 gCount;
void bump(void *);
void f(void *arg0)
{
  s32 *p;
  s32 *q;
  s32 rowsum;
  s32 col;
  s32 row;
  u8 *base;
  void *rec;
  rec = *(void **) ((char *) arg0 + 0x6C);
  p = (&gCount) + (*((u8 *) (((char *) rec) + 0x33))) * 7;
  p += *((u8 *) (((char *) rec) + 0x34));
  if ((*p) == *((s32 *) ((char *) rec + 0x18)))
  {
    bump(rec);
  }
  p = (&gCount) + (*((u8 *) (((char *) rec) + 0x33))) * 7;
  p += *((u8 *) (((char *) rec) + 0x34));
  *p += 1;
  col = *((u8 *) (((char *) rec) + 0x34));
  row = (*((u8 *) (((char *) rec) + 0x33)));
  rowsum = row * 7;
  q = &gCount;
  q += rowsum;
  q += col;
  base = gStart;
  if ((*q) == *(s32 *)(col * 4 + (rowsum * 4 + base)))
  {
    bump(arg0);
  }
}
'''


def test_every_access_of_both_tables_is_one_child_first():
    out = table.variants(SOURCE, 'f')
    assert out[0][0] == 'row_major_table'
    whole = out[0][1]
    assert 'extern s32 gCount[][7];' in whole and 'extern s32 gStart[][7];' in whole
    assert 'if (gCount[row][col] == gStart[row][col])' in whole
    assert 'gCount[(*((u8 *) (((char *) rec) + 0x33)))][*((u8 *) (((char *) rec) + 0x34))] += 1;' in whole
    assert 'if (gCount[(*((u8 *) (((char *) rec) + 0x33)))][*((u8 *) (((char *) rec) + 0x34))] == *((s32 *)' in whole
    assert 'p +=' not in whole and 'q +=' not in whole and 'base = gStart' not in whole


def test_each_table_alone_follows():
    out = [text for _, text in table.variants(SOURCE, 'f')]
    assert len(out) == 3
    count_only = next(text for text in out if 'extern u8 gStart[];' in text)
    assert 'extern s32 gCount[][7];' in count_only and 'base = gStart;' in count_only
    start_only = next(text for text in out if 'extern s32 gStart[][7];' in text and 'extern s32 gCount;' in text)
    assert 'gStart[row][col]' in start_only and '*q' in start_only


def test_a_pointer_that_is_used_beyond_the_next_statement_is_left_alone():
    source = SOURCE.replace('  *p += 1;\n', '  *p += 1;\n  bump(p);\n')
    assert all('extern s32 gCount;' in text for _, text in table.variants(source, 'f'))


def test_a_table_the_function_reads_another_way_is_left_alone():
    source = SOURCE.replace('  rec = *', '  bump(&gCount);\n  rec = *')
    assert all('extern s32 gCount;' in text for _, text in table.variants(source, 'f'))


def test_a_row_expression_that_is_not_one_operand_is_left_alone():
    source = SOURCE.replace('(&gCount) + (*((u8 *) (((char *) rec) + 0x33))) * 7;\n  p += *((u8 *) (((char *) rec) + 0x34));\n  if',
                            '(&gCount) + col + row * 7;\n  p += *((u8 *) (((char *) rec) + 0x34));\n  if')
    assert all('extern s32 gCount;' in text for _, text in table.variants(source, 'f'))


def test_no_variants_for_a_function_without_the_shape():
    assert table.variants('extern s32 gCount;\nvoid g(void)\n{\n  gCount = 1;\n}\n', 'g') == []
