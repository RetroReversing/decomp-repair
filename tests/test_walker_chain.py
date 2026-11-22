"""load_scale_fold, byte_selector_merge and switch_tail_scope_unwrap: the three steps of one 130 -> 0 match.

The synthetic source has the saved best's shape from a KMC (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) N64 walker over a
byte-coded record stream: a raw byte local, a masked copy that the switch reads, a reload local at the loop's tail, an
identical-arm guard on a never-set local, a `do { } while (0)` around the last cases and a padding local inside it.
Scores (the app's exact judge, one function): saved best 130; selector merge 70; fold the two scaled arms 40; unwrap 0."""
from decomprepair import byte_selector_merge, load_scale_fold, registry, switch_tail_scope_unwrap

BEST = '''void walk(u8 *a0, s32 *total, s32 *extra, s32 *kind)
{
  u8 *p = a0;
  long raw;
  long span;
  s32 reload;
  u32 opcode;
  unsigned int count;
  *total = 0;
  *extra = 0;
  raw = *p;
  if (((u8) raw) != 12)
  {
    if (reload || kind)
    {
      opcode = raw & 255;
    }
    else
    {
      opcode = raw & 255;
    }
    do
    {
      switch (opcode)
      {
        case 9:
          p += 4;
          break;

        case 0:
          *total = (*total) + p[1];
          p++;
          span = *p;
          *kind = 0;
          span *= 3;
          p += span + 1;
          break;

 do { case 1: { long long phantom_wide = span; } *total = (*total) + p[1]; p++; span = *p; *kind = 1; span *= 3; goto double_size; case 3: *total = (*total) + p[1]; p++; span = *p; *kind = 3; p += span + 1; break; case 2: *total = (*total) + p[1]; p++; span = *p; *kind = 2; double_size: span *= 2; p += span + 1; break; case 4: p += 4; *extra += 1; break; } while (0);
      }

      reload = *p;
      opcode = reload & 255;
    }
    while (reload != 12);
  }
}
'''


def test_the_scale_folds_into_every_arm_and_into_each_alone():
    out = load_scale_fold.variants(BEST, 'walk')
    assert [f for f, _ in out] == ['load_scale_fold'] * 3
    both, first, second = (t for _, t in out)
    assert 'span = *p * 3;' in both and 'span *= 3' not in both
    assert 'span = *p * 3;\n          *kind = 0;' in first and 'span *= 3; goto' in first
    assert 'span = *p * 3; *kind = 1;' in second and 'span *= 3;\n' in second


def test_the_scale_is_left_where_the_value_is_read_between_or_the_local_is_narrow():
    read = 'void f(u8 *p, s32 *o)\n{\n  s32 m;\n  m = *p;\n  *o = m;\n  m *= 3;\n  *o += m;\n}\n'
    assert load_scale_fold.variants(read, 'f') == []
    branch = 'void f(u8 *p, s32 *o)\n{\n  s32 m;\n  m = *p;\n  if (*o) m = 1;\n  m *= 3;\n  *o += m;\n}\n'
    assert load_scale_fold.variants(branch, 'f') == []
    constant = 'void f(s32 *o)\n{\n  s32 m;\n  m = 2;\n  *o = 1;\n  m *= 3;\n  *o += m;\n}\n'
    assert load_scale_fold.variants(constant, 'f') == []
    wide = 'void f(u8 *p, s32 *o)\n{\n  s32 m;\n  m = p[1] + 1;\n  *o = 1;\n  m *= 3;\n  *o += m;\n}\n'
    assert '(p[1] + 1) * 3' in load_scale_fold.variants(wide, 'f')[0][1]


def test_the_three_byte_locals_become_one_u8_with_and_without_the_guard_collapse():
    out = byte_selector_merge.variants(BEST, 'walk')
    assert out and {f for f, _ in out} == {'byte_selector_merge'}
    collapsed = out[0][1]
    assert 'u8 opcode;' in collapsed and 'raw' not in collapsed and 'reload' not in collapsed
    assert 'opcode = opcode & 255' not in collapsed and 'while (opcode != 12)' in collapsed
    assert 'if (reload || kind)' not in collapsed and 'if (opcode || kind)' not in collapsed
    assert any('if (opcode || kind)' in t for _, t in out)


def test_a_chain_that_is_read_after_a_later_load_is_not_merged():
    stale = ('void f(u8 *p, s32 *o)\n{\n  long raw;\n  long next;\n  u32 op;\n  raw = *p;\n  op = raw & 255;\n'
             '  next = p[1];\n  *o = raw;\n  op = next & 255;\n}\n')
    assert byte_selector_merge.variants(stale, 'f') == []
    wide = 'void f(s16 *p, s32 *o)\n{\n  long raw;\n  u32 op;\n  raw = *p;\n  op = raw & 255;\n  *o = raw + op;\n}\n'
    assert byte_selector_merge.variants(wide, 'f') == []


def test_the_wrapper_over_the_last_cases_comes_off_with_its_padding_local():
    out = switch_tail_scope_unwrap.variants(BEST, 'walk')
    assert [f for f, _ in out] == ['switch_tail_scope_unwrap']
    text = out[0][1]
    assert 'while (0)' not in text and 'phantom_wide' not in text and ' case 1: *total' in text


def test_a_wrapper_that_does_not_end_the_switch_or_holds_a_continue_stays():
    inner = BEST.replace('case 4: p += 4; *extra += 1; break; } while (0);\n      }',
                         'case 4: p += 4; *extra += 1; break; } while (0); case 5: p += 1; break;\n      }')
    assert switch_tail_scope_unwrap.variants(inner, 'walk') == []
    loop = BEST.replace('case 4: p += 4;', 'case 4: continue; p += 4;')
    assert switch_tail_scope_unwrap.variants(loop, 'walk') == []


def test_the_registry_declares_all_three():
    names = {entry.module if hasattr(entry, 'module') else str(entry) for entry in registry.declared()}
    for module in ('load_scale_fold', 'byte_selector_merge', 'switch_tail_scope_unwrap'):
        assert any(module in n for n in names)
