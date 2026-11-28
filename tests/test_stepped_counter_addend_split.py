from decomprepair import stepped_counter_addend_split as split

SOURCE = '''void f(void *rec)
{
  s16 height;
  s32 count;
  *((s32 *) (((char *) rec) + 0x3C)) += *((s32 *) (((char *) rec) + 0x40));
  count = (*((s32 *) (((char *) rec) + 0x34))) + 1;
  *((s32 *) (((char *) rec) + 0x34)) = count;
  height = (*((u16 *) (((char *) rec) + 0x3A))) + (count >> 2);
  *((s16 *) (((char *) rec) + 0x6A)) = height;
}
'''


def test_whole_combination_in_one_child():
    first = split.variants(SOURCE, 'f')[0][1]
    assert ('do { *((s32 *) (((char *) rec) + 0x3C)) += *((s32 *) (((char *) rec) + 0x40)); '
            'count = *((s32 *) (((char *) rec) + 0x34)); } while (0);\n'
            '  height = *((u16 *) (((char *) rec) + 0x3A));\n'
            '  do { do { do { count++; *((s32 *) (((char *) rec) + 0x34)) = count; count >>= 2; '
            '} while (0); } while (0); } while (0);\n'
            '  height += count;\n') in first


def test_members_of_one_record_and_plain_children():
    source = '''struct R { s32 timer; s32 base; u16 height; };
void f(struct R *r)
{
  s32 t;
  s32 h;
  t = r->timer + 1;
  r->timer = t;
  h = (t >> 1) + r->base;
  r->height = h;
}
'''
    children = [code for _, code in split.variants(source, 'f')]
    assert any('  t = r->timer;\n  h = r->base;\n  t++; r->timer = t; t >>= 1;\n  h += t;\n' in code
               for code in children)


def test_declines_when_not_the_same_program():
    # the addend is the stored place, or overlaps it
    assert not split.variants(SOURCE.replace('+ 0x3A', '+ 0x36'), 'f')
    # the counter is read again
    assert not split.variants(SOURCE.replace('= height;\n}', '= height + count;\n}'), 'f')
    # a float sum rounds differently when split
    assert not split.variants(SOURCE.replace('s16 height;', 'f32 height;'), 'f')
    # another base may point at the counter
    assert not split.variants(SOURCE.replace('(u16 *) (((char *) rec)', '(u16 *) (((char *) other)'), 'f')
    assert not split.variants(SOURCE.replace('s32 count;', 'volatile s32 count;'), 'f')
