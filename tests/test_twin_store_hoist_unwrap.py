"""twin_store_hoist_unwrap: a second store of one value moved up beside its first, with the one-shot scopes dropped.

Synthetic shape of a 142-instruction KMC object-setup function (saved best 60; 120 with the store moved alone, 60 with
the scopes dropped alone, 0 with both)."""
from decomprepair import twin_store_hoist_unwrap as t

SOURCE = '''s32 g(void *);
s32 setup(u32 a, u8 b, u8 c, u8 d)
{
  u8 *p;
  u8 v;
  v = b;
  p = (u8 *) a;
  do
  {
    *((s16 *) (p + 0x4E)) = v;
    *((s8 *) (p + 0xC0)) = 0;
    *((u8 *) (p + 0x52)) = c;
    *((s16 *) (p + 0x50)) = v;
    *((u8 *) (p + 0x53)) = d;
  }
  while (0);
  return g(p);
}
'''


def moved(source):
    return source.replace('''    *((s8 *) (p + 0xC0)) = 0;
    *((u8 *) (p + 0x52)) = c;
    *((s16 *) (p + 0x50)) = v;
''', '''    *((s16 *) (p + 0x50)) = v;
    *((s8 *) (p + 0xC0)) = 0;
    *((u8 *) (p + 0x52)) = c;
''')


def families(source):
    return {family: text for family, text in t.variants(source, 'setup')}


def test_twin_moves_beside_its_first_store_alone_and_with_the_scopes_dropped():
    out = families(SOURCE)
    hoisted = out['twin_store_hoist']
    assert hoisted.index('0x4E') < hoisted.index('0x50') < hoisted.index('0xC0') < hoisted.index('0x52')
    assert hoisted.count('0x50') == 1 and 'while (0)' in hoisted
    unwrapped = out['twin_store_hoist_unwrap']
    assert unwrapped.index('0x4E') < unwrapped.index('0x50') < unwrapped.index('0xC0')
    assert 'while' not in unwrapped and 'do' not in unwrapped.replace('double', '')


def test_declines_a_value_that_reads_memory_or_calls():
    for value in ('*q', 'q[1]', 'h(v)', 'p->x'):
        assert not t.variants(SOURCE.replace('0x50)) = v;', '0x50)) = ' + value + ';')
                              .replace('0x4E)) = v;', '0x4E)) = ' + value + ';'), 'setup')


def test_declines_a_value_the_function_does_not_declare():
    source = SOURCE.replace('= v;', '= gGlobal;')
    assert not t.variants(source, 'setup')


def test_declines_a_value_whose_address_is_taken():
    source = SOURCE.replace('  v = b;', '  v = b;\n  g(&v);')
    assert not t.variants(source, 'setup')


def test_declines_overlapping_offsets_and_other_bases():
    assert not t.variants(SOURCE.replace('0x50)) = v', '0x4F)) = v'), 'setup')
    assert not t.variants(SOURCE.replace('(p + 0x52)', '(q + 0x52)'), 'setup')


def test_declines_when_the_two_stores_already_touch():
    source = SOURCE.replace('''    *((s8 *) (p + 0xC0)) = 0;
    *((u8 *) (p + 0x52)) = c;
''', '')
    assert not t.variants(source, 'setup')


def test_registered():
    assert t.REPAIR['families'] == t.FAMILIES
