"""operand_access_helpers: a script-op handler's operand reads and destination write as inline helpers, with the carrier and clamp edits that pay off only together.

Shape of a 148-instruction KMC handler (saved best 1135, m2c's ladders: `temp = word >> 0x10;` preludes, scaled temporaries,
`((i + 1) - 1) <= (16 - 1)` limits, a `u8` carrier of the opcode and a clamp into a narrow local). The five children were
judged: the reads alone 1580, with the write 1185, with the carrier 320, with the other clamp polarity 865, all four 0."""
import pathlib
import re

from decomprepair import operand_access_helpers as w
from decomprepair import registry

M2C = """s32 store_slot(void *, s32, s16);
extern s16 slot_table;
s32 run_op(void *arg0, void *arg1, s32 arg2)
{
  s32 value;
  s32 temp_v0_2;
  s32 temp_v0_4;
  s32 var_a2;
  s16 __repair_saved_narrow;
  s32 var_s1;
  u32 temp_v0_3;
  unsigned char temp_v1;
  u32 temp_v1_2;
  u32 temp_v1_3;
  u32 temp_v1_4;
  u32 temp_v1_5;
  u32 temp_v1_6;
  u32 temp_v1_7;
  u32 var_a0;
  unsigned char var_v1;
  temp_v1 = *((u32 *) (((char *) arg1) + 4));
  if ((*((u8 *) (((char *) arg1) + 0))) != 0)
  {
    var_s1 = fetch_slot(arg0, temp_v1 & 0xFF);
  }
  else
  {
    temp_v1_2 = temp_v1 & 0x1F;
    
    if (temp_v1_2 < 0x10U)
    {
      value = (s32) (*((s16 *) (((char *) ((temp_v1_2 * 2) + arg0)) + 0x180)));
    }
    else
    {
      value = (s32) (*((s16 *)((char *)&slot_table + temp_v1_2 * 2)));
    }
    var_s1 = value;
  }
  var_v1 = arg2 & 0xFF;
  if (var_v1 == 4)
  {
    var_a0 = ((u32) (*((u32 *) (((char *) arg1) + 4)))) >> 8;
  }
  else
  {
    temp_v1_3 = *((u32 *) (((char *) arg1) + 4));
    temp_v1_4 = temp_v1_3 >> 0x10;
    if ((temp_v1_3 >> 8) & 0xFF)
    {
      var_a0 = fetch_slot(arg0, temp_v1_4 & 0xFF);
    }
    else
    {
      temp_v0_3 = temp_v1_4 & 0x1F;
      temp_v0_2 = temp_v0_3 * 2;
      if (((temp_v0_3 + 1) - 1) <= (0x10U - 1))
      {
        var_a0 = (u32) (*((s16 *) (((char *) (temp_v0_2 + arg0)) + 0x180)));
      }
      else
      {
        var_a0 = (u32) (*((s16 *)((char *)&slot_table + temp_v0_2)));
      }
    }
    var_v1 = arg2 & 0xFF;
  }
  switch ((u32)((short) var_v1))
  {
    case 0:

    case 4:
      temp_v0_4 = ((s16) var_s1) + ((s16) var_a0);
      break;

    case 1:
      temp_v0_4 = ((s16) var_s1) - ((s16) var_a0);
      break;

    case 2:
      temp_v0_4 = ((s16) var_s1) * ((s16) var_a0);
      break;

    case 3:
      if (((s16) var_a0) != 0)
    {
      temp_v0_4 = ((s16) var_s1) / ((s16) var_a0);
    }
    else
    {
      temp_v0_4 = 0;
    }
      break;

  }

  temp_v0_3 = *((u32 *) (((char *) arg1) + 0));
  temp_v1_6 = temp_v0_3 >> 0x10;
  if (temp_v0_4 < (-0x8000))
  {
    {
      var_a2 = -0x8000; __repair_saved_narrow = (s16) var_a2;
    }
  }
  else
  {
    {
      var_a2 = 0x7FFF; __repair_saved_narrow = (s16) var_a2;
    }
    if (temp_v0_4 <= 0x7FFF)
    {
      __repair_saved_narrow = temp_v0_4;
    }
  }
  if ((temp_v0_3 >> 8) & 0xFF)
  {
    store_slot(arg0, temp_v1_6 & 0xFF, (s16) __repair_saved_narrow);
    return 0;
  }
  temp_v1_6 &= 0x1F;
  temp_v0_4 = temp_v1_6 * 2;
  if (temp_v1_6 < 0x10U)
  {
    *((s16 *) (((char *) (temp_v0_4 + arg0)) + 0x180)) = (s16) __repair_saved_narrow;
  }
  else
  {
    *((s16 *) (((u8 *) (&slot_table)) + temp_v0_4)) = (s16) __repair_saved_narrow;
  }
  return 0;
}
"""


def by_family(found, family):
    return [text for name, text in found if name == family]


def test_the_five_children_are_the_steps_alone_and_together():
    found = w.variants(M2C, 'run_op')
    assert [name for name, _ in found] == [w.FAMILY, w.FAMILY, w.BUNDLE, w.BUNDLE, w.BUNDLE]
    assert len({text for _, text in found}) == 5


def test_each_read_is_one_call_of_a_private_inline_helper_with_its_own_arguments():
    text = w.variants(M2C, 'run_op')[0][1]
    assert text.count('static __inline__ s32 read_operand(void *p, u8 sel, u8 idx)') == 1
    assert 'value = fetch_slot(p, idx & 0xFF);' in text and 'idx &= 0x1F;\n    if (idx < 0x10U)' in text
    assert 'value = *((s16 *) (((char *) ((idx * 2) + p)) + 0x180));' in text
    assert 'value = *((s16 *)((char *)&slot_table + idx * 2));' in text
    assert 'var_s1 = read_operand(arg0, (*((u8 *) (((char *) arg1) + 0))), (*((u32 *) (((char *) arg1) + 4))));' in text
    assert ('var_a0 = read_operand(arg0, ((*((u32 *) (((char *) arg1) + 4))) >> 8) & 0xFF, '
            '((*((u32 *) (((char *) arg1) + 4))) >> 0x10));') in text
    body = text.split('run_op(')[1]
    assert 'temp_v1_3' not in body and 'temp_v0_2' not in body and 'value;' not in body
    assert text.index('static __inline__') < text.index('s32 run_op(')


def test_the_write_is_a_helper_fed_two_unmasked_locals_and_the_clamp_is_flipped():
    text = w.variants(M2C, 'run_op')[4][1]
    assert 'static __inline__ void write_operand(void *p, u8 sel, u8 idx, s16 v)' in text
    assert 'store_slot(p, idx & 0xFF, v);' in text and '= v;' in text
    assert 'u32 sel = (*((u32 *) (((char *) arg1) + 0))) >> 8;' in text
    assert 'u32 idx = ((*((u32 *) (((char *) arg1) + 0))) >> 0x10);' in text
    assert 'if (temp_v0_4 >= (-0x8000))' in text and 'write_operand(arg0, sel, idx, __repair_saved_narrow);' in text
    assert text.count('s16 __repair_saved_narrow;') == 1 and text.rstrip().endswith('return 0;\n}')
    plain = w.variants(M2C, 'run_op')[1][1]
    assert 'if (temp_v0_4 < (-0x8000))' in plain


def test_the_opcode_carrier_becomes_the_expression_it_always_held():
    text = w.variants(M2C, 'run_op')[2][1]
    assert 'var_v1' not in text and 'if ((arg2 & 0xFF) == 4)' in text and 'switch (arg2 & 0xFF)' in text
    assert 'var_v1' in w.variants(M2C, 'run_op')[1][1]


def test_other_spellings_and_shapes_are_left_alone():
    assert w.variants('void f(void)\n{\n    g();\n}\n', 'f') == []
    assert w.variants(M2C.replace('return 0;\n}', 'goto x;\n}', 1), 'run_op') == []
    taken = w.variants('static __inline__ s32 read_operand(void);\n' + M2C, 'run_op')
    assert taken == []
    no_write = M2C.replace('return 0;\n  }\n  temp_v1_6', 'return 1;\n  }\n  temp_v1_6')
    assert {name for name, _ in w.variants(no_write, 'run_op')} == {w.FAMILY}


def test_it_declares_itself_for_every_caller_lane():
    repair = registry.get('operand_access_helpers')
    assert repair is not None and set(repair.families) == set(w.FAMILIES)
    assert registry.problems(repair) == []
    assert re.search(r'^REPAIR\s*=', pathlib.Path(w.__file__).read_text(), re.M)
