"""A halfword countdown timer and its guarded loop: proposals only, nothing is compiled here."""
from decomprepair.halfword_countdown_shapes import COUNTDOWN, COUNTER, FAMILY, SUCCESSOR, variants

# The shape of a menu-update function (GCC 2.7.2, KMC, N64) at 310 with two rows wrong: a loop over a record's entries
# that runs only while a halfword timer is zero, and the timer's own countdown. m2c wrote the word arithmetic.
BEFORE = '''extern void *gMenu;
extern void *gState;
extern s32 sink(void *, s32);
void f(void)
{
  s32 i;
  s16 t;
  unsigned short temp;
  s32 next;
  void *state;
  void *menu;
  t = *((s16 *) (((char *) gMenu) + 0x7C));
  if (t == 0)
  {
    i = 0;
    state = gState;
    if ((((u32) t) + 1) <= ((u8) (*((u8 *) (((char *) state) + 5)))))
    {
      do
      {
        sink(state, i & 0xFFFF);
        i += 1;
      }
      while (((u32) (i & 0xFFFF)) < ((u8) (*((u8 *) (((char *) state) + 5)))));
    }
  }
  menu = gMenu;
  temp = *((s16 *) (((char *) menu) + 0x7C));
  if (((s16) temp) > 0)
  {
    next = temp - 1;
    *((s16 *) (((char *) menu) + 0x7C)) = next;
    if ((next << 0x10) == 0)
    {
      sink(state, 1);
    }
  }
}
'''
FIELD = '*((s16 *) (((char *) menu) + 0x7C))'


def by_family(source, arch='mips'):
    return {family: text for family, text in variants(source, 'f', arch)}


def test_the_successor_compare_keeps_the_unsigned_test_of_the_timer():
    text = by_family(BEFORE)[SUCCESSOR]
    assert 'if (((u32) t) < ((u8)' in text and '+ 1)' not in text.split('do')[0]
    assert 'i & 0xFFFF' in text  # the counter is left to its own family


def test_the_counter_read_only_through_its_mask_is_a_halfword():
    text = by_family(BEFORE)[COUNTER]
    assert '  u16 i;' in text and 's32 i;' not in text
    assert text.count('& 0xFFFF') == BEFORE.count('& 0xFFFF')  # reads are untouched: u16 gives the same values


def test_the_field_countdown_is_a_compound_decrement_of_the_field():
    text = by_family(BEFORE)[COUNTDOWN]
    assert f'if ({FIELD} > 0)' in text and f'{FIELD} -= 1;' in text and f'if ({FIELD} == 0)' in text
    assert 'next = temp - 1' not in text and '<< 0x10' not in text


def test_the_combination_is_one_child_that_has_all_three_edits():
    # each alone left the function at 310, 310 and 455; the three together were exact
    combo = by_family(BEFORE)[FAMILY]
    assert 'if (((u32) t) < ' in combo and '  u16 i;' in combo and f'{FIELD} -= 1;' in combo


def test_a_counter_read_bare_stays_a_word():
    bare = BEFORE.replace('sink(state, i & 0xFFFF);', 'sink(state, i);')
    assert COUNTER not in by_family(bare)
    assert FAMILY in by_family(bare)  # the other two edits still combine


def test_the_counter_must_be_stepped_by_one():
    other = BEFORE.replace('i += 1;', 'i += 2;')
    assert COUNTER not in by_family(other)


def test_only_an_unsigned_successor_is_folded():
    signed = BEFORE.replace('(((u32) t) + 1) <=', '((t) + 1) <=')
    assert SUCCESSOR not in by_family(signed)


def test_the_temps_must_be_the_countdown_s_own():
    shared = BEFORE.replace('      sink(state, 1);', '      sink(state, next);')
    assert COUNTDOWN not in by_family(shared)


def test_a_lone_applicable_edit_makes_no_combination():
    only = BEFORE.replace('(((u32) t) + 1) <=', '(t >= 0) &&').replace('i & 0xFFFF', 'i')
    found = by_family(only)
    assert COUNTDOWN in found and FAMILY not in found


def test_only_mips_is_proposed():
    assert variants(BEFORE, 'f', 'ppc') == []


def test_a_missing_function_proposes_nothing():
    assert variants(BEFORE, 'g', 'mips') == []


def test_signed_zero_guard_and_masked_counter_are_repaired_together():
    from decomprepair.halfword_countdown_shapes import SIGNED_ENTRY

    source = """extern s32 count;
void f(void) {
    s32 timer;
    s32 index;
    s32 *bound;
    if (timer) { tick(); } else { tick(); }
    timer = next();
    if (timer == 0) {
        start();
        index = 0;
        bound = &count;
        if (((u32) timer) < ((u32) (*bound))) {
            do {
                visit(index & 0xff);
                index++;
            } while ((index & 0xffff) < *bound);
        }
    }
}
"""
    result = dict(variants(source, 'f', 'mips'))[SIGNED_ENTRY]
    assert 'u16 index;' in result
    assert 'if (timer < *bound)' in result
    assert '    tick();' in result
    assert 'if (timer)' not in result
    for before, after in (
        ('        start();', '        timer = next();'),
        ('visit(index & 0xff);', 'visit(index);'),
        ('extern s32 count;', 'extern u32 count;'),
    ):
        assert SIGNED_ENTRY not in dict(variants(source.replace(before, after), 'f', 'mips'))
    assert variants(source, 'f', 'arm') == []
