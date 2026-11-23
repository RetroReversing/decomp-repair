"""A hand-built stack frame written as the plain locals reload spills."""
from decomprepair import registry
from decomprepair.frame_struct_unwrap import FAMILY, FOLD, variants

SOURCE = """void build(u8 *p, s32 model, s32 a3, s32 enable, s32 *commands)
{
  struct
  {
    s32 texture;
    GfxPair *start;
    s32 unused;
    volatile s32 vertexTransform;
    u8 padding[7];
    u8 emit;
  } state;
  u32 savedSpace[8];
  s32 i;
  state.vertexTransform = a3;
  state.texture = -1;
  state.emit = enable;
  for (i = 0; i < p[1]; i++)
  {
    gfxAppendTexture(p, &state.texture, state.vertexTransform);
  }
  if ((state.emit << 24) != 0)
  {
    finish(&state.start, state.vertexTransform);
  }
}
"""


def test_the_struct_keeps_only_the_members_whose_address_is_passed_on():
    child = dict(variants(SOURCE, 'build'))[FAMILY]
    assert 'struct\n  {\n    s32 texture;\n    GfxPair *start;\n  } state;' in child
    assert 'volatile' not in child and 'padding' not in child and 'unused' not in child
    assert 's32 state_vertexTransform;' in child and 'u8 state_emit;' in child
    assert 'savedSpace' not in child
    assert 'gfxAppendTexture(p, &state.texture, state_vertexTransform);' in child
    assert 'if ((state_emit << 24) != 0)' in child


def test_a_word_copy_of_a_parameter_is_read_as_the_parameter():
    child = dict(variants(SOURCE, 'build'))[FOLD]
    assert 'state_vertexTransform' not in child and 'gfxAppendTexture(p, &state.texture, a3);' in child
    # the byte narrows its parameter: it stays a local of its own
    assert 'u8 state_emit;' in child and 'state_emit = enable;' in child


def test_a_whole_struct_address_or_a_written_parameter_is_declined():
    assert variants(SOURCE.replace('&state.start', '&state'), 'build') == []
    child = dict(variants(SOURCE.replace('state.texture = -1;', 'state.texture = -1;\n  a3 = 0;'), 'build'))
    assert FOLD not in child


def test_registry_declares_the_families():
    repair = registry.get('frame_struct_unwrap')
    assert repair is not None and registry.problems(repair) == []
    assert FAMILY in repair.families and FOLD in repair.families
