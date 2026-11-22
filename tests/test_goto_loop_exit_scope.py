"""A backward-goto loop's pointer step moved into the body, and the loop wrapped in `do { } while (0)`."""
from decomprepair import goto_loop_exit_scope as repair
from decomprepair.goto_loop_exit_scope import FAMILY, variants

# A two-arm table search (KMC GCC 2.7.2, 110 -> 0 with the per-arm base split after it): each arm counts a bit length,
# then walks a halfword table down with m2c's `*(p--)` in the condition and a `goto` back.
TWO_SCANS = '''s32 f(void *a, u32 q) {
  u16 *p;
  u16 *r;
  s32 i;
  s32 j;
  if (q < 5) {
    i = 11;
    p = (u16 *) (((char *) a) + 0x16);
    loop_1:
    if (((u16) (*(p--))) >= q) {
      i = i - 1;
      goto loop_1;
    }
    *(s16 *) a = i;
  } else {
    j = 11;
    r = (u16 *) (((char *) a) + 0x16);
    loop_2:
    if (((u16) inline_fn(*(r--))) >= q) {
      j -= 1;
      goto loop_2;
    }
    *(s16 *) a = j;
  }
  return 0;
}
'''


def _squash(text):
    return ' '.join(text.split())


def test_the_step_goes_into_the_body_and_the_loop_is_wrapped_in_the_first_child():
    first = variants(TWO_SCANS, 'f')[0]
    assert first[0] == FAMILY
    out = _squash(first[1])
    assert 'if (((u16) (*p)) >= q) { p--; i = i - 1; goto loop_1; } } while (0);' in out
    assert 'do { loop_1:' in out
    assert 'if (((u16) inline_fn(*r)) >= q) { r--; j -= 1; goto loop_2; } } while (0);' in out
    assert 'do { loop_2:' in out
    assert '(p--)' not in out and '(r--)' not in out


def test_each_step_is_also_offered_alone_and_the_wrapper_alone():
    outs = [_squash(text) for _, text in variants(TWO_SCANS, 'f')]
    assert any('(*p)' in t and 'do {' not in t and '(r--)' in t for t in outs)  # the first loop's step only
    assert any('(p--)' in t and 'do { loop_1:' in t and 'p--;' not in t for t in outs)  # the first loop's wrapper only
    assert any('do {' not in t and '(p--)' not in t and '(r--)' not in t for t in outs)  # every step, no wrapper


def test_a_pointer_read_after_the_loop_keeps_its_step():
    read = TWO_SCANS.replace('*(s16 *) a = i;', '*(s16 *) a = *p;')
    outs = [_squash(text) for _, text in variants(read, 'f')]
    assert outs and all('(p--)' in t for t in outs)
    assert any('(*r)' in t and 'r--;' in t for t in outs)


def test_a_pointer_set_again_before_it_is_read_may_move_its_step():
    again = TWO_SCANS.replace('*(s16 *) a = i;\n  } else {', '*(s16 *) a = i;\n    p = r;\n  } else {')
    outs = [_squash(text) for _, text in variants(again, 'f')]
    assert any('(*p)' in t and 'p--;' in t for t in outs)


def test_a_label_jumped_to_from_elsewhere_is_left_alone():
    shared = TWO_SCANS.replace('  return 0;', '  if (q == 7) goto loop_1;\n  return 0;')
    outs = [_squash(text) for _, text in variants(shared, 'f')]
    assert all('do { loop_1:' not in t and '(p--)' in t for t in outs)


def test_a_loop_that_is_already_wrapped_is_not_wrapped_twice():
    first = variants(TWO_SCANS, 'f')[0][1]
    assert all(_squash(text).count('do { do {') == 0 for _, text in variants(first, 'f'))
    assert variants(first, 'f') == []


def test_no_variant_without_a_goto_loop():
    assert variants('s32 f(s32 a) {\n  while (a > 3) {\n    a -= 1;\n  }\n  return a;\n}\n', 'f') == []


def test_the_module_declares_itself_for_mips_only():
    assert repair.REPAIR['archs'] == ('mips',) and repair.REPAIR['families'] == (FAMILY,)


# A search's leftover: the loop block closes on an identical-arm guard that only keeps a value live (KMC gcc 2.7.2, 150).
GUARDED = TWO_SCANS.replace("""      i = i - 1;
      goto loop_1;
""", """      if (k || a) {
        i = i - 1;
        goto loop_1;
      } else {
        i = i - 1;
        goto loop_1;
      }
""").replace("  s32 j;\n", "  s32 j;\n  s32 k;\n")


def test_an_identical_arm_guard_closing_the_loop_is_collapsed_in_the_child():
    first = _squash(variants(GUARDED, 'f')[0][1])
    assert 'k || a' not in first
    assert 'do { loop_1: if (((u16) (*p)) >= q) { p--; i = i - 1; goto loop_1; } } while (0);' in first


def test_a_guard_with_a_side_effect_or_different_arms_is_kept():
    effect = GUARDED.replace('k || a', 'k++')
    assert all('k++' in _squash(text) for _, text in variants(effect, 'f') if 'loop_1' in text)
    different = GUARDED.replace('        i = i - 1;\n        goto loop_1;\n      } else {\n        i = i - 1;', '        i = i - 2;\n        goto loop_1;\n      } else {\n        i = i - 1;')
    assert all('k || a' in _squash(text) for _, text in variants(different, 'f') if 'loop_1' in text)
