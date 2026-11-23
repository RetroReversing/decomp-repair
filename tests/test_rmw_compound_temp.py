"""rmw_compound_temp: a field's read-modify-write respelled through a compound temporary.

Synthetic shape of a 795-instruction KMC object spawner (635 -> 180): a word update written `w = F; w = (w & M) | K; F = w;`
became `w &= M; w |= K;` and the flag update `F |= 2;` became `F = F | 2;`; the spelling alone left 690 -> 690 with the
statements in the other order, which is why one child respells every site."""
from decomprepair import rmw_compound_temp as s

SOURCE = '''void mark(void *m, void *rec) {
  s32 w;
  *(s16 *) ((char *) m + 0x20) = 0x14;
  *(u16 *) ((char *) m + 0x1E) |= 2;
  w = *(s32 *) ((char *) m + 0x28);
  w = (w & ~0xFC) | 0x10;
  *(s32 *) ((char *) m + 0x28) = w;
  *(s32 *) ((char *) m + 0x2C) = (*(s32 *) ((char *) m + 0x2C) & ~0xFC) | 0x1C;
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'mark') if family == s.FAMILY]


def test_each_site_alone_and_every_site_together():
    texts = _texts()
    assert len(texts) == 4
    compound = [t for t in texts if 'w &= ~0xFC;\n  w |= 0x10;' in t or 'w &= ~0xFC; w |= 0x10;' in t]
    assert len(compound) >= 1


def test_the_temporary_word_form_keeps_one_assignment_per_step():
    texts = _texts()
    one = [t for t in texts if 'rmw3 = *(s32 *) ((char *) m + 0x2C); rmw3 &= ~0xFC; rmw3 |= 0x1C;' in t]
    assert len(one) == 2
    assert all('  s32 rmw3;' in t for t in one)


def test_every_word_site_gets_a_temporary_of_its_own():
    source = SOURCE.replace('  w = *(s32 *) ((char *) m + 0x28);\n  w = (w & ~0xFC) | 0x10;\n  *(s32 *) ((char *) m + 0x28) = w;\n',
                            '  *(s32 *) ((char *) m + 0x28) = (*(s32 *) ((char *) m + 0x28) & ~0xFC) | 0x10;\n')
    both = [t for t in _texts(source) if 'rmw2 &= ~0xFC' in t and 'rmw3 &= ~0xFC' in t]
    assert len(both) == 1 and '  s32 rmw2;' in both[0] and '  s32 rmw3;' in both[0]


def test_the_flag_or_becomes_a_plain_read_or_write():
    texts = _texts()
    assert any('*(u16 *) ((char *) m + 0x1E) = *(u16 *) ((char *) m + 0x1E) | 2;' in t for t in texts)


def test_a_side_effect_in_the_field_is_left_alone():
    source = SOURCE.replace('*(u16 *) ((char *) m + 0x1E) |= 2;', 'tab[n++] |= 2;')
    assert not any('n++' in t and '= tab[n++] | 2' in t for t in _texts(source))
