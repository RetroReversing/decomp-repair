"""A byte offset stepped beside a loop counter, written off the counter."""
from decomprepair import counter_derived_offset as c

SOURCE = '''s32 f(u16 id, u8 flag)
{
  s32 i;
  char *p;
  if (D_80100000)
  {
    {
      s32 offset = 0;
      for (i = 0; i < D_80100004; i++, offset += 4)
      {
        p = *((char **) (((char *) D_80100008) + offset));
        if ((*((u16 *) (p + 4))) == id)
        {
          return g(p, flag);
        }
      }
    }
  }
  return -1;
}
'''


def test_offset_written_off_the_counter_shift_first():
    # A 86-instruction N64 function: 115 -> 20 with this edit alone (0 with the do-while(0) unwrap as well); the
    # `i * 4` spelling stayed at 790 because cse folds it into a stepped pointer.
    (family, shift), (_, product) = c.variants(SOURCE, 'f')
    assert family == 'counter_derived_offset'
    assert 's32 offset' not in shift and 'for (i = 0; i < D_80100004; i++)\n' in shift
    assert 'p = *((char **) (((char *) D_80100008) + (i << 2)));' in shift
    assert '(i * 4)' in product and 'i << 2' not in product


def test_non_power_of_two_step_has_only_the_product():
    only, = c.variants(SOURCE.replace('offset += 4', 'offset += 0x18'), 'f')
    assert '(i * 24)' in only[1]


def test_left_alone_when_the_offset_escapes_the_loop():
    # read after the loop, assigned in it, address taken, or a counter that starts elsewhere or is stepped in the body
    assert c.variants(SOURCE.replace('    }\n  }\n  return -1;', '    }\n    h(offset);\n  }\n  return -1;'), 'f') == []
    assert c.variants(SOURCE.replace('        p = *', '        offset = 8;\n        p = *'), 'f') == []
    assert c.variants(SOURCE.replace('g(p, flag)', 'g(&offset, flag)'), 'f') == []
    assert c.variants(SOURCE.replace('for (i = 0;', 'for (i = 1;'), 'f') == []
    assert c.variants(SOURCE.replace('        p = *', '        i++;\n        p = *'), 'f') == []
    assert c.variants(SOURCE.replace('i++, offset += 4', 'i += 2, offset += 4'), 'f') == []
    assert c.variants(SOURCE.replace('s32 offset = 0;', 'h();'), 'f') == []
