import re

from decomprepair.entry_guard_sink import CONST_FAMILY, COPY_FAMILY, FAMILY, LOAD_FAMILY, variants

SOURCE = """void walk(s16 *list, void *src, void *dst, s32 flag)
{
  struct { s16 rot[3]; u8 mats[0x900]; } local;
  s32 count;
  s16 *cur;
  void *in;
  void *out;
  count = 0; in = src;
  {
    u8 *base = local.mats;
    if ((*list) >= 0)
    {
      cur = list; out = dst;
      again:
      {
        s32 index = *cur;
 do { use(&local.rot[0], base + index * 48, *(s32 *) in); cur += 16; in += 4; out += 12; count++; if (*cur >= 0) { goto again; } } while (0);
      }
    }
  }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def _by_family():
    out = {}
    for family, text in variants(SOURCE, 'walk'):
        out.setdefault(family, []).append(_flat(text))
    return out


def test_the_guard_reads_through_a_const_pointer():
    out = _by_family()[CONST_FAMILY]
    assert len(out) == 1 and 'if ((*(const s16 *) list) >= 0)' in out[0]
    assert 'u8 *base = local.mats;' in out[0]  # only the read changes


def test_the_pointer_copies_follow_the_guard_in_source_order_of_the_target():
    out = _by_family()[COPY_FAMILY][0]
    assert 'u8 * base; if' in out or 'u8 *base; if' in out
    assert '{ base = local.mats; cur = list; out = dst; in = src;' in out
    assert 'count = 0; in = src;' not in out and 'count = 0;' in out


def test_the_loop_head_load_moves_into_the_do():
    out = _by_family()[LOAD_FAMILY][0]
    assert 's32 index; do { index = *cur;' in out


def test_the_whole_set_is_one_child_and_the_pairs_are_offered():
    children = variants(SOURCE, 'walk')
    labels = [family for family, _ in children]
    assert labels.count(FAMILY) == 4 and len(children) == 7
    whole = _flat(children[-1][1])
    assert 'const s16' in whole and 'base = local.mats; cur = list; out = dst; in = src;' in whole \
        and 's32 index; do { index = *cur;' in whole


def test_a_field_read_guard_is_cast_const_too():
    source = SOURCE.replace('s16 *list,', 'struct Node *list,').replace('if ((*list) >= 0)', 'if (list->tag >= 0)') \
        .replace('s32 index = *cur;', 's32 index = *(s32 *) cur;').replace('s16 *cur;', 'struct Node *cur;') \
        .replace('cur += 16;', 'cur += 1;')
    out = [_flat(text) for family, text in variants(source, 'walk') if family == CONST_FAMILY]
    assert out and '((const struct Node *) list)->tag >= 0' in out[0]


def test_nothing_without_a_pointer_parameter_guard_or_when_code_loops_first():
    assert variants(SOURCE.replace('(*list) >= 0', 'flag >= 0'), 'walk') == []
    assert variants(SOURCE.replace('s16 *list', 'const s16 *list'), 'walk') == []
    looped = SOURCE.replace('    u8 *base = local.mats;', '    u8 *base = local.mats;\n    while (flag) { flag--; }')
    assert variants(looped, 'walk') == []
    called = SOURCE.replace('    u8 *base = local.mats;', '    u8 *base = local.mats;\n    init(base);')
    assert variants(called, 'walk') == []


def test_a_copy_the_else_path_or_the_code_after_reads_stays_put():
    source = SOURCE.replace('      }\n    }\n  }\n}', '      }\n    }\n    count = (s32) in;\n  }\n}')
    out = [_flat(text) for family, text in variants(source, 'walk') if family == COPY_FAMILY]
    assert out and 'in = src;' in out[0].split('{ base')[0]
