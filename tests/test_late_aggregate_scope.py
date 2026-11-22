from decomprepair.late_aggregate_scope import FAMILY, variants

SOURCE = """void f(void *arg)
{
  float pos[3];
  float diff[3];
  int status;
  float pad;
  if (ready(arg)) {
    if (look(arg, &status)) {
      reset(arg);
    }
    pos[0] = fetch(arg);
    diff[0] = pos[0] - 1.0f;
    use(pos, diff);
    if (status == 1) {
      mark(arg);
    }
  }
}
"""


def test_arrays_move_into_a_block_after_the_call_that_takes_a_scalars_address():
    found = variants(SOURCE, 'f')
    assert {family for family, _ in found} == {FAMILY} and len(found) == 2  # both slot orders
    assert found[1][1].index('float diff[3]') < found[1][1].index('float pos[3]')
    child = found[0][1]
    assert '  float pos[3];\n  float diff[3];\n  int status;' not in child
    assert child.index('&status') < child.index('float pos[3]') < child.index('pos[0] = fetch')
    assert child.index('float diff[3]') < child.index('pos[0] = fetch')
    # the new block closes after the last use, inside the `if` that held it
    assert child.count('{') == child.count('}')
    assert child.replace(' ', '').replace('\n', '').count('floatpos[3];') == 1


def test_declined_when_the_slot_order_cannot_change():
    assert not variants(SOURCE.replace('&status', 'status'), 'f')
    assert not variants(SOURCE.replace('int status;', 'volatile int status;'), 'f')
    # an array already used before the call stays where it is
    [(_, kept)] = variants(SOURCE.replace('if (look(', 'pos[1] = 0; if (look('), 'f')
    assert '\n  float pos[3];\n' in kept and '\n  float diff[3];' not in kept
    # a use after the block that would hold the arrays keeps them at the top
    assert not variants(SOURCE.replace('  }\n}\n', '  }\n  use(pos, diff);\n}\n'), 'f')
    assert not variants(SOURCE.replace('mark(arg);', 'mark(arg); goto done;'), 'f')


def test_no_child_when_every_use_is_at_the_functions_top_level():
    flat = """void f(void)
{
  float v[3];
  int s;
  look(&s);
  v[0] = 1.0f;
  use(v);
}
"""
    assert not variants(flat, 'f')
