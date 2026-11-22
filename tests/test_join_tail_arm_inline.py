"""join_tail_arm_inline: a join's store copied into each arm with the arm's own temporaries folded into it.

Shape of a 180-instruction menu function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): the shared store of a
three-way table choice written in each arm took the score 110 -> 20 (with the second such join), and 0 with the
byte-width pair of `local_width_group`. The source below is made up; it only has that shape."""
import re

from decomprepair import join_tail_arm_inline as arm_inline
from decomprepair import registry

HEAD = '''extern s32 gTable[];
extern s32 D_a;
extern s32 D_b;
extern void *gState;
'''

ONE_SITE = HEAD + '''void f(void *p, s32 i, s32 flag)
{
  void *row;
  s32 value;
  s32 low;
  if (i != 0) {
    row = *(void **)((s8 *)p + 8);
    value = gTable[i];
    low = *(u8 *)((s8 *)gState + 0x30);
  } else {
    if (flag & 1) {
      row = *(void **)((s8 *)p + 8);
      value = D_a;
      low = *(u8 *)((s8 *)row + 0x13);
    } else {
      row = *(void **)((s8 *)p + 8);
      value = D_b;
      low = *(u8 *)((s8 *)row + 0x13);
    }
  }
  *(s32 *)((s8 *)row + 0x10) = (value & ~0xFF) | low;
}
'''


def test_the_store_goes_into_each_arm_with_its_temporaries_folded_and_the_pointer_stays_shared():
    [(family, text)] = arm_inline.variants(ONE_SITE, 'f')
    assert family == 'join_tail_arm_inline'
    stores = re.findall(r'\*\(s32 \*\)\(\(s8 \*\)row \+ 0x10\) = ([^;]+);', text)
    assert stores == ['((gTable[i]) & ~0xFF) | (*(u8 *)((s8 *)gState + 0x30))',
                      '(D_a & ~0xFF) | (*(u8 *)((s8 *)row + 0x13))',
                      '(D_b & ~0xFF) | (*(u8 *)((s8 *)row + 0x13))']
    assert 'value' not in text and 'low' not in text          # assignments and declarations gone
    assert text.count('row = *(void **)((s8 *)p + 8);') == 3   # the pointer stays one shared local, set in each arm
    assert text.rstrip().endswith('}\n  }\n}')                  # nothing is left after the if/else


def test_a_temporary_read_after_the_join_is_not_folded_but_the_others_are():
    source = ONE_SITE.replace('void f(', 's32 f(').replace('(value & ~0xFF) | low;', '(value & ~0xFF) | low;\n  return value;')
    [(_, text)] = arm_inline.variants(source, 'f')
    assert text.count('value = ') == 3 and 'low' not in text   # `value` stays an assignment per arm; `low` folded


def test_a_store_between_a_temporary_and_the_copy_keeps_the_load_where_it_was():
    source = ONE_SITE.replace('    value = gTable[i];',
                              '    value = gTable[i];\n    *(s32 *)((s8 *)p + 4) = 1;')
    [(_, text)] = arm_inline.variants(source, 'f')
    assert 'value = gTable[i];' in text                     # the load would move across a store: left alone
    assert '(D_a & ~0xFF)' in text and 'low' not in text    # the other arms and the byte fold as before


def test_arms_that_return_are_left_alone_and_one_falling_arm_is_no_site():
    source = ONE_SITE.replace('low = *(u8 *)((s8 *)row + 0x13);', 'return;')
    assert arm_inline.variants(source, 'f') == []


TWO_SITES = HEAD + '''void g(void *p, s32 i, s32 j)
{
  void *row;
  s32 value;
  s32 low;
  if (i != 0) {
    row = *(void **)((s8 *)p + 8);
    value = gTable[i];
    low = *(u8 *)((s8 *)gState + 0x30);
  } else {
    row = *(void **)((s8 *)p + 12);
    value = D_a;
    low = *(u8 *)((s8 *)row + 0x13);
  }
  *(s32 *)((s8 *)row + 0x10) = (value & ~0xFF) | low;
  if (j != 0) {
    row = *(void **)((s8 *)p + 16);
    value = gTable[j];
    low = *(u8 *)((s8 *)gState + 0x31);
  } else {
    row = *(void **)((s8 *)p + 20);
    value = D_b;
    low = *(u8 *)((s8 *)row + 0x14);
  }
  *(s32 *)((s8 *)row + 0x10) = (value & ~0xFF) | low;
}
'''


def test_every_site_is_offered_alone_and_all_together():
    children = [text for _, text in arm_inline.variants(TWO_SITES, 'g')]
    assert len(children) == 3
    both = children[-1]
    assert 'value' not in both and 'low' not in both
    assert all(child != TWO_SITES for child in children)
    assert sum('value' in child for child in children[:2]) == 2   # each alone leaves the other site as it was


def test_the_module_declares_itself_for_the_apps_registry():
    repair = registry.get('join_tail_arm_inline')
    assert repair is not None and repair.families == ('join_tail_arm_inline',)
    assert registry.problems(repair) == []


def test_a_variable_the_tail_does_not_list_is_folded_last_not_a_crash(monkeypatch):
    """The arms can name a private variable the tail's own list lacks; sorting by the list's index raised
    ValueError, which stopped every family's proposals for that source."""
    real = arm_inline._private_regions

    def with_extra(text, name, only=None):
        found = real(text, name, only=only)
        if found:
            region = next(iter(next(iter(found.values()))[1]))
            found = {**found, 'not_in_names': (None, [region], None)}
        return found
    monkeypatch.setattr(arm_inline, '_private_regions', with_extra)
    arm_inline.variants(ONE_SITE, 'f')
