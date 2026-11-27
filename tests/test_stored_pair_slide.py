from decomprepair import registry
from decomprepair.stored_member_readback import FAMILY as READ
from decomprepair.stored_member_readback import variants as readback
from decomprepair.stored_pair_slide import FAMILY, READBACK, variants

P = '(((char *) arg0) + {})'
BEST = f"""void func(void *arg0)
{{
  s16 height;
  s32 timer;
  s32 phase;
  do {{ timer = (*((s32 *) {P.format('0x34')})) + 1;
  *((s32 *) {P.format('0x34')}) = timer;
  phase = (*((s32 *) {P.format('0x3C')})) + 0x3DD1;
  *((s32 *) {P.format('0x3C')}) = phase;
  *((s8 *) {P.format('0x73')}) = ~(phase >> 0xC);
  *((s8 *) {P.format('0x72')}) = ~(phase >> 0xC);
  *((s8 *) {P.format('0x71')}) = ~(phase >> 0xC);
  height = (*((u16 *) {P.format('0x3A')})) + (timer >> 1);
  *((s16 *) {P.format('0x6A')}) = height;
  if ((height & 0xFFFF) > ((*((s32 *) {P.format('0x38')})) + 0x20))
  {{
    other(arg0);
  }} }} while (0);
}}
"""


def squeeze(text):
    return ''.join(text.split())


def test_the_wrapped_cast_spelling_is_read_back():
    found = [child for family, child in readback(BEST, 'func') if family == READ]
    assert found and 'height & 0xFFFF' not in found[0]
    assert squeeze(f"((*((u16 *) {P.format('0x6A')})))>") in squeeze(found[0])


def test_the_pair_moves_with_the_read_back_and_the_fence_open():
    wanted = squeeze(f"""*((s32 *) {P.format('0x34')}) = timer;
      height = (*((u16 *) {P.format('0x3A')})) + (timer >> 1);
      *((s16 *) {P.format('0x6A')}) = height;
      phase =""")
    found = [child for family, child in variants(BEST, 'func') if family == READBACK and wanted in squeeze(child)]
    assert any('while (0)' not in child and 'height & 0xFFFF' not in child for child in found)


def test_the_pair_does_not_pass_the_value_it_reads_or_a_call():
    moved = [child for family, child in variants(BEST, 'func') if family == FAMILY]
    assert moved
    for child in moved:
        assert child.index('timer = (') < child.index('height = (')  # never above the value it reads
    called = BEST.replace('  height = (', '  other(arg0);\n  height = (')
    for _, child in variants(called, 'func'):
        assert child.index('other(arg0);') < child.index('height = (')


def test_a_copy_between_locals_is_not_a_store():
    assert variants('void func(void) {\n  s32 a;\n  s32 b;\n  s32 c;\n  a = 1;\n  b = a;\n  c = 2;\n}\n', 'func') == []


def test_registered():
    assert any(FAMILY in repair.families for repair in registry.declared())
