from decomprepair.byte_flag_chain import FAMILIES, REPAIR, variants

HEADER = """typedef unsigned char u8;
typedef unsigned short u16;
typedef signed int s32;
typedef struct { u8 first; u8 pad[3]; } Bonus;
typedef struct { u8 a; u8 b; } Out;
extern Bonus bonus_table[];
"""

SOURCE = """void update(Out *out, s32 idx, s32 on, s32 n)
{
  u8 v;
  int bonus;
  s32 s1;
  s32 t2;
  s32 one;
  s1 = 0;
  bonus = 0;
  if (n) {
    bonus = bonus_table[n].first;
  }
  s1 = (u16) bonus != 0;
  v = out[idx].a;
  if (on) v |= 8;
  if (on) one = 1; else if (!on) one = 1; else one = 0;
  out[(unsigned long long) idx].a = v;
  if (!one) return;
  v = out[idx].b;
  s1 = (v >> 2) & 1; t2 = s1 ^ ((v >> 3) & 1);
  out[idx].b = t2;
}
"""


def _by_family(source=SOURCE):
    return {family: text for family, text in variants(source, 'update', HEADER)}


def test_the_split_read_and_store_becomes_one_compound_update():
    text = _by_family()['guarded_or_compound']
    assert 'out[idx].a |= on ? 8 : 0;' in text
    assert 'v = out[idx].a;' not in text and '= v;' not in text
    assert text.index('out[idx].a |= on ? 8 : 0;') < text.index('if (on) one = 1;')  # the flag test stays after it


def test_a_value_read_again_before_it_is_reassigned_keeps_the_split_form():
    source = SOURCE.replace('if (!one) return;', 'if (!one) return;\n  out[1].b = v;')
    assert 'guarded_or_compound' not in _by_family(source)


def test_a_statement_between_that_reads_the_memory_keeps_the_split_form():
    source = SOURCE.replace('  if (on) one = 1; else if (!on) one = 1; else one = 0;', '  one = out[idx].a;')
    assert 'guarded_or_compound' not in _by_family(source)


def test_a_word_local_read_as_a_halfword_holding_a_byte_is_declared_u16():
    text = _by_family()['cast_read_narrow']
    assert '  u16 bonus;' in text and '  int bonus;' not in text


def test_a_word_assigned_a_wide_value_is_not_narrowed():
    source = SOURCE.replace('bonus = bonus_table[n].first;', 'bonus = n * 1000;')
    assert 'cast_read_narrow' not in _by_family(source)


def _all(family, source=SOURCE):
    return [text for name, text in variants(source, 'update', HEADER) if name == family]


def test_the_dead_scratch_name_gets_a_local_of_its_own():
    texts = _all('dead_scratch_web_split')
    assert any('s1_web = (v >> 2) & 1; t2 = s1_web ^ ((v >> 3) & 1);' in text and 's1 = (u16) bonus != 0;' in text
               for text in texts)  # the earlier, longer web keeps the name


def test_a_name_read_after_the_web_is_not_split():
    source = SOURCE.replace('  out[idx].b = t2;', '  out[idx].b = t2;\n  out[0].a = 3;\n  out[1].a = s1;')
    assert not any('s1_web' in text for text in _all('dead_scratch_web_split', source))


def test_the_three_edits_are_also_offered_as_one_child():
    both = _by_family()['byte_flag_chain']
    assert 'out[idx].a |= on ? 8 : 0;' in both and 'u16 bonus;' in both and 's1_web = (v' in both


def test_the_module_declares_itself():
    assert REPAIR['families'] == FAMILIES and REPAIR['variants'] is variants
