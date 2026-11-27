"""m2c's rotated two-test scan loop written back as one `while` over a record view of the table."""
from decomprepair import registry, scan_loop_while

SOURCE = '''
extern s32 gRanges;
void find_range(u32 address, s32 *out)
{
  s32 found;
  u32 i;
  void *entry;
  i = 0;
  if ((address < ((u32) (*((u32 *) (((char *) (&gRanges)) + 0))))) || ((found = 0U < 0x20U, (((u32) (*((u32 *) (((char *) (&gRanges)) + 8)))) < address) != 0)))
  {
    do
    {
      for (;;)
      {
        i += 1;
        entry = (void *) (i * 0x10);
        entry = (void *) (((char *) entry) + ((s32) (&gRanges)));
        if (address <= (((u32) (*((u32 *) (((char *) entry) + 0)))) - 1))
        {
          continue;
        }
        break;
      }
    }
    while (((u32) (*((u32 *) (((char *) entry) + 8)))) < address);
    found = i < 0x20U;
  }
  *out = found;
}
'''


def test_writes_the_loop_as_a_while_over_records():
    ((family, child),) = scan_loop_while.variants(SOURCE, 'find_range')
    assert family == 'scan_loop_while'
    assert 'typedef struct { u32 f0; u8 pad4[4]; u32 f8; u8 padC[4]; } ScanEntry;\nvoid find_range' in child
    assert ('while (address < ((ScanEntry *) &gRanges)[i].f0 || ((ScanEntry *) &gRanges)[i].f8 < address)\n'
            '  {\n      i++;\n  }\n  found = i < 0x20U;\n  *out = found;') in child
    assert 'for (;;)' not in child and 'do' not in child.split('i = 0;')[1]


def test_leaves_a_loop_whose_entry_test_differs():
    other = SOURCE.replace('(&gRanges)) + 8)))) < address) != 0', '(&gRanges)) + 4)))) < address) != 0')
    assert scan_loop_while.variants(other, 'find_range') == []


def test_leaves_a_loop_whose_pointer_is_read_afterwards():
    used = SOURCE.replace('*out = found;', '*out = found + *(s32 *) entry;')
    assert scan_loop_while.variants(used, 'find_range') == []
    assigned = SOURCE.replace('*out = found;', 'entry = (void *) 0;\n  *out = found;')
    assert scan_loop_while.variants(assigned, 'find_range')


def test_is_declared():
    assert registry.problems(registry.get('scan_loop_while')) == []
