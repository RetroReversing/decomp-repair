from decomprepair.byte_copy_split_weight import COPY, FAMILIES, FAMILY, POINTER, REREAD, SHIFT, WEIGHT, variants

SOURCE = """
void walk(void *obj, s8 flag)
{
  s32 idx;
  u8 *p;
  u8 *tbl;
  tbl = *((u8 **) (((u8 *) obj) + 0x6C));
  for (;;)
  {
    p = *((u8 **) (((u8 *) obj) + 0x68));
    idx = (s8) p[0xF];
    p[0xF] = (u8) (((u8) idx) + tbl[(idx * 8) + 0x1FE]);
    if (check(tbl, idx))
    {
      (*((u8 **) (((u8 *) obj) + 0x68)))[0xF] = idx;
      break;
    }
  }
}
"""


def by_family(source=SOURCE):
    found = {}
    for family, text in variants(source, 'walk'):
        found.setdefault(family, []).append(text)
    return found


def test_it_declares_its_families():
    assert set(FAMILIES) == {FAMILY, REREAD, WEIGHT, SHIFT}


def test_the_sum_rereads_its_byte_and_the_late_store_reads_a_copy_made_before_it():
    [text] = by_family()[REREAD]
    assert f'u8 idx{COPY};' in text
    assert f'idx{COPY} = idx;\n    p[0xF] = (u8) (p[0xF] + tbl[(idx * 8) + 0x1FE]);' in text
    assert f'(*((u8 **) (((u8 *) obj) + 0x68)))[0xF] = idx{COPY};' in text
    assert '(u8) idx' not in text


def test_the_combination_also_sends_the_store_through_a_wrapped_pointer_of_its_own():
    texts = by_family()[FAMILY]
    first = texts[0]
    assert f'u8 *{POINTER};' in first and f'u8 idx{COPY};' in first
    assert (f'{POINTER} = *((u8 **) (((u8 *) obj) + 0x68)); do {{ do {{ {POINTER}[0xF] = idx{COPY}; }} while (0); }} while (0);'
            in first)
    assert 'do { do { do {' in texts[1]
    assert any('(tbl + (idx<<3))[0x1FE]' in text for text in texts)  # the shifted-base form on top of a child


def test_the_wrapped_store_alone_and_the_shifted_base_alone_are_offered():
    found = by_family()
    [weight] = found[WEIGHT]
    assert f'{POINTER}[0xF] = idx;' in weight and 'u8 idx_bc' not in weight
    [shifted] = found[SHIFT]
    assert '(tbl + (idx<<3))[0x1FE]' in shifted and '(u8) idx' in shifted


def test_children_are_not_offered_twice():
    for family, text in variants(SOURCE, 'walk'):
        if family not in (FAMILY, REREAD):
            continue
        assert [family for family, _ in variants(text, 'walk') if family in (FAMILY, REREAD)] == []


def test_leaves_alone_a_sum_whose_byte_was_not_loaded_from_the_same_place():
    other = SOURCE.replace('idx = (s8) p[0xF];', 'idx = (s8) q[0xF];')
    assert REREAD not in by_family(other) and FAMILY not in by_family(other)


def test_leaves_alone_a_value_stored_twice_late():
    twice = SOURCE.replace('      break;', '      (*((u8 **) (((u8 *) obj) + 0x68)))[0x10] = idx;\n      break;')
    assert REREAD not in by_family(twice)
