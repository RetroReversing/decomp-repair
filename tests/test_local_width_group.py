"""local_width_group: word locals that copy each other, narrowed to the cast they all carry, together.

A 180-instruction menu function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) needed its selected-row index and the
loop copy of it both `u8` (20 -> 0): either alone scored worse (620, 1490). The source below is made up."""
import re

from decomprepair import local_width_group, local_width_repairs, registry

SOURCE = '''extern u8 gRows[];
extern void use(s32);
void f(s32 start, s32 count)
{
  s32 sel;
  u32 cur;
  s32 other;
  sel = start;
  cur = sel;
  while ((u8)cur < count) {
    if (gRows[(u8)cur * 4] & 0x80) {
      sel = cur;
      break;
    }
    cur++;
  }
  other = sel;
  use((u8)sel);
  use(other);
}
'''


def test_two_copy_connected_locals_are_narrowed_together():
    [(family, text)] = local_width_group.variants(SOURCE, 'f')
    assert family == 'local_width_group'
    assert 'u8 sel;' in text and 'u8 cur;' in text
    assert 's32 other;' in text                         # no cast of its own: not a member


def test_the_single_local_family_offers_each_alone_and_never_the_pair():
    alone = local_width_repairs.variants(SOURCE, 'f')
    assert alone and not any(re.search(r'\bu8 sel;', t) and re.search(r'\bu8 cur;', t) for t in alone)


def test_a_member_without_a_narrow_cast_makes_no_group():
    source = SOURCE.replace('(u8)cur', 'cur').replace('(u8)cur * 4', 'cur * 4')
    assert local_width_group.variants(source, 'f') == []


def test_locals_that_do_not_copy_each_other_are_not_a_group():
    source = SOURCE.replace('  cur = sel;\n', '  cur = 0;\n').replace('sel = cur;', 'sel = 1;')
    assert local_width_group.variants(source, 'f') == []


def test_an_address_taken_or_volatile_local_is_left_alone():
    assert local_width_group.variants(SOURCE.replace('use((u8)sel);', 'use(*(&sel));'), 'f') == []
    assert local_width_group.variants(SOURCE.replace('s32 other;', 'volatile s32 other;'), 'f') == []


def test_the_module_declares_itself_for_the_apps_registry():
    repair = registry.get('local_width_group')
    assert repair is not None and repair.families == ('local_width_group',)
    assert registry.problems(repair) == []
