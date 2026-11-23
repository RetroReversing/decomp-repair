"""A `*q` cursor stepped beside the counter, indexed by it, with the loop's address locals written at their reads."""
import re

from decomprepair import registry
from decomprepair.cursor_deref_index import FAMILY, variants

SOURCE = """void setup(void)
{
  char *t4;
  void **p;
  s32 i;

  if (0 < gCount) {
    i = 0;
    {
      t4 = ((char *) (&gFlags)) - 1;
    }
    p = (void **) (((char *) (&gSlot4)) - 0x10);
    do {
      if (*p == NULL) {
        make(i);
        use(*p);
        t4[0] &= ~(1 << i);
        t4[-1] &= ~(1 << i);
        *(s32 *)((u8 *)*p + 0x100) |= 0x100;
      }
      i += 1;
      p += 1;
    } while (gCount > i);
  }
}
"""


def _children():
    return [child for family, child in variants(SOURCE, 'setup') if family == FAMILY]


def test_the_cursor_is_indexed_and_the_address_local_written_at_its_reads():
    child = _children()[0]
    assert 'if (p[i] == NULL) {' in child and 'use(p[i]);' in child and '((u8 *)p[i] + 0x100)' in child
    assert 'p += 1;' not in child and 'i += 1;' in child and 'while (gCount > i);' in child
    assert '(((char *) (&gFlags)) - 1)[0] &= ~(1 << i);' in child
    assert '(((char *) (&gFlags)) - 1)[-1] &= ~(1 << i);' in child
    assert not re.search(r'\bt4\b', child)
    assert 'p = (void **) (((char *) (&gSlot4)) - 0x10);' in child


def test_the_indexed_cursor_alone_is_offered_too():
    children = _children()
    assert any('t4[0]' in child and 'p[i]' in child for child in children)


def test_a_forward_test_and_a_postincrement_are_read_the_same_way():
    source = SOURCE.replace('while (gCount > i);', 'while (i < gCount);').replace('p += 1;', 'p++;')
    child = [c for f, c in variants(source, 'setup')][0]
    assert 'if (p[i] == NULL) {' in child and 'p++;' not in child


def test_a_product_is_not_a_read_through_the_cursor():
    source = SOURCE.replace('use(*p);', 'use(*p);\n        use2(n * p);')
    assert variants(source, 'setup') == []


def test_programs_whose_meaning_would_change_are_declined():
    # a read after the step, the cursor read after the loop, a jump in the body, a counter not started at 0
    assert variants(SOURCE.replace('      p += 1;\n', '      p += 1;\n      use(*p);\n'), 'setup') == []
    assert variants(SOURCE.replace('    } while (gCount > i);\n', '    } while (gCount > i);\n    use(*p);\n'), 'setup') == []
    assert variants(SOURCE.replace('make(i);', 'if (i) break;\n        make(i);'), 'setup') == []
    assert variants(SOURCE.replace('    i = 0;\n', '    i = 1;\n'), 'setup') == []
    # an address local also read outside the loop stays a local
    kept = SOURCE.replace('    do {', '    use(t4);\n    do {')
    assert all('t4[0]' in child for child in [c for f, c in variants(kept, 'setup')])


def test_registry_declares_the_family():
    repair = registry.get('cursor_deref_index')
    assert repair is not None and FAMILY in repair.families
