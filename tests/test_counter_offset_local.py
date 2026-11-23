"""A byte offset stepped beside a loop counter, written as a local of the body computed from the counter."""
from decomprepair import registry
from decomprepair.counter_offset_local import FAMILY, variants

SOURCE = '''void walk(s32 n)
{
  s32 i;
  s32 offset;
  for (i = 0, offset = 0; i < n; offset += 0x24, i++)
  {
    f32 t = *((f32 *) (((u8 *) (&D_80100020)) + offset));
    use((&D_80100018) + i * 9, t);
  }
}
'''


def test_the_offset_becomes_a_local_of_the_body_off_the_counter():
    # 340 -> 120 on a 529-instruction N64 function; the same product written in each read was 910
    (family, text), = variants(SOURCE, 'walk')
    assert family == FAMILY
    assert 'for (i = 0; i < n; i++)\n  {\n    s32 offset = i * 0x24;\n' in text
    assert 's32 offset;\n' not in text and 'offset += ' not in text
    assert '(((u8 *) (&D_80100020)) + offset)' in text


def test_the_other_step_order_and_decimal_steps_are_read_too():
    (_, text), = variants(SOURCE.replace('offset += 0x24, i++', 'i++, offset += 36'), 'walk')
    assert 's32 offset = i * 36;' in text


def test_an_offset_read_after_the_loop_assigned_in_it_or_a_counter_stepped_twice_is_left_alone():
    assert variants(SOURCE.replace('}\n}\n', '}\n  use(offset, 0);\n}\n'), 'walk') == []
    assert variants(SOURCE.replace('    use(', '    offset = 4;\n    use('), 'walk') == []
    assert variants(SOURCE.replace('    use(', '    i++;\n    use('), 'walk') == []
    assert variants(SOURCE.replace('i = 0, offset = 0', 'i = 0, offset = 4'), 'walk') == []
    assert variants(SOURCE.replace('  s32 offset;\n', ''), 'walk') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'counter_offset_local' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'counter_offset_local':
            assert registry.problems(repair) == []
