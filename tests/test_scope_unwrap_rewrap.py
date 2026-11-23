"""An outer one-shot scope removed and one long load chain given a scope of its own, as one child."""
from decomprepair import registry
from decomprepair.scope_unwrap_rewrap import FAMILY, variants

CHAIN = ('d = ((*((f32 *) (((u8 *) g) + 0x10))) * (*((f32 *) (((u8 *) p) + 0xC))) + (*((f32 *) (((u8 *) g) + 0x14))) '
         '* (*((f32 *) (((u8 *) p) + 0x10))) + (*((f32 *) (((u8 *) g) + 0x18))) * (*((f32 *) (((u8 *) p) + 0x14)))); D_80100010 = d;')
SOURCE = f'''void walk(void *g, void *p)
{{
  f32 d;
  if (p != NULL)
  {{
    do
    {{
      do
      {{
        {CHAIN}
        if (!(d > (-0.2f)))
        {{
          goto next;
        }}
        h(p);
        next:
        p = *((void **) p);
      }}
      while (p != NULL);
    }}
    while (0);
  }}
}}
'''


def test_the_wrapper_comes_off_and_the_chain_gets_a_scope_with_and_without_its_guard():
    # a 529-instruction N64 function: the wrapper alone was 505, the chain's scope alone 970, both together 460
    found = variants(SOURCE, 'walk')
    assert {family for family, _ in found} == {FAMILY}
    assert len(found) == 2
    alone, guarded = (text for _, text in found)
    for text in (alone, guarded):
        assert text.count('while (0);') == 1 and text.count('do\n') == 2
    assert 'do\n        {\n        d = (' in alone and alone.index('while (0);') < alone.index('if (!(d')
    assert guarded.index('while (0);') > guarded.index('goto next;')


def test_a_wrapper_with_a_break_or_no_loop_or_a_short_chain_gives_nothing():
    assert variants(SOURCE.replace('h(p);', 'if (c) break;'), 'walk') == []
    assert variants(SOURCE.replace('while (p != NULL);', 'while (0);'), 'walk') == []
    assert variants(SOURCE.replace(CHAIN, 'd = *((f32 *) (((u8 *) p) + 0xC)); D_80100010 = d;'), 'walk') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'scope_unwrap_rewrap' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'scope_unwrap_rewrap':
            assert registry.problems(repair) == []
