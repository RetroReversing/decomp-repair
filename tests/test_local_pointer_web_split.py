"""local_pointer_web_split: a pointer local assigned twice in one block, one variable per assignment.

Synthetic shape of a 795-instruction KMC object spawner (3545 -> 2435): one `tbl` pointer served two lookups of the same
table, and the second lookup's argument-register preference pulled the first lookup's pointer into the wrong register."""
from decomprepair import local_pointer_web_split as s

SOURCE = '''void f(s16 id, void *obj) {
  void **tbl;
  s32 n;
  n = 0;
  if (obj != NULL) {
    tbl = &sTable[id];
    put(*tbl, 1);
    set(*tbl, 3);
    spawn(obj);
    tbl = &sTable[id];
    clear(*tbl);
    clear2(*tbl);
  }
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'f') if family == s.FAMILY]


def test_the_second_lookup_gets_its_own_variable():
    [text] = _texts()
    assert '  void **tbl2;\n' in text
    assert 'tbl2 = &sTable[id];\n    clear(*tbl2);\n    clear2(*tbl2);' in text
    assert 'put(*tbl, 1);' in text and 'set(*tbl, 3);' in text


def test_a_mention_after_the_block_stops_the_rewrite():
    source = SOURCE.replace('    clear2(*tbl);\n  }\n', '    clear2(*tbl);\n  }\n  last(*tbl);\n')
    assert _texts(source) == []


def test_a_loop_around_the_block_stops_the_rewrite():
    source = SOURCE.replace('  if (obj != NULL) {', '  while (n < 3) {\n    n++;')
    assert _texts(source) == []


def test_a_goto_stops_the_rewrite():
    source = SOURCE.replace('    spawn(obj);\n', '    spawn(obj);\n    goto out;\n').replace('  }\n}', '  }\nout:\n  return;\n}')
    assert _texts(source) == []


def test_an_integer_is_not_split():
    source = SOURCE.replace('void **tbl;', 'int tbl;').replace('&sTable[id]', 'id').replace('*tbl', 'tbl')
    assert _texts(source) == []
