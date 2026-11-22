from decomprepair import retry_goto_scope_repairs as repair

# The shape of a rejection loop (GCC 2.7.2, KMC, N64): pick an entry, compare it with every slot but the owner's own,
# start over when one is too close. 475 as m2c wrote it, 480 for the `if` form, 0 with the pinned goto as well.
SOURCE = '''extern s32 D_count;
extern s32 D_slots[];
extern s32 D_pick(s32);
extern f32 D_far(void *, s32);
void f(void *arg0)
{
  s16 slot;
  s16 next;
  s32 pick;
  retry:
  slot = 0;
  pick = D_pick(8);
  if (D_count > 0)
  {
    for (;;)
    {
      if ((slot == (*((s8 *) (((char *) arg0) + 0x182))))) { next = slot + 1; goto skip; }
      next = slot + 1;
      if (!(!(D_far(arg0, D_slots[slot] + 0x24) < 3.0f))) goto retry;
      skip:
      slot = next;
      if (next >= D_count) break;
    }
  }
}
'''


def test_the_if_form_with_the_pinned_goto_is_the_first_proposal():
    family, text = repair.variants(SOURCE, 'f')[0]
    assert family == 'retry_goto_scope'
    assert ('if (slot != (*((s8 *) (((char *) arg0) + 0x182))))\n'
            '      {\n'
            '        if (D_far(arg0, D_slots[slot] + 0x24) < 3.0f) { do { goto retry; } while (0); }\n'
            '      }\n'
            '      next = slot + 1;\n'
            '      slot = next;\n'
            '      if (next >= D_count) break;') in text
    assert 'skip' not in text


def test_the_halves_are_proposed_alone_too():
    found = [text for _, text in repair.variants(SOURCE, 'f')]
    assert len(found) == 3
    plain, pinned_only = found[1], found[2]
    assert 'goto retry;' in plain and 'while (0)' not in plain and 'skip' not in plain
    assert 'while (0)' in pinned_only and 'skip:' in pinned_only


def test_a_forward_goto_and_other_architectures_are_left_alone():
    forward = '''extern s32 D_x;
void f(void)
{
  if (D_x) goto done;
  D_x = 1;
  done:
  D_x = 2;
}
'''
    assert repair.variants(forward, 'f') == []
    assert repair.variants(SOURCE, 'f', arch='ppc') == []


def test_an_already_pinned_goto_is_not_wrapped_again():
    pinned = repair.variants(SOURCE, 'f')[0][1]
    assert repair.variants(pinned, 'f') == []
