"""A call that indexes one table twice: the base and a narrow index load staged before it (a probe handler, 240 -> 180)."""
from decomprepair import registry
from decomprepair.call_table_stage import FAMILY_BASE, FAMILY_BOTH, FAMILY_INDEX, variants

SOURCE = """extern void *gTracks[];
extern s16 gRows[];
void unlink(void *, void *, void *);
void drop(char *rec, s32 k)
{
  s32 row;
  row = gRows[k];
  unlink(rec, gTracks[row], gTracks[*((s8 *) (rec + 0x182))]);
  unlink(rec, gTracks[row], rec);
}
"""


def by_family(source=SOURCE, header=''):
    out = {}
    for family, text in variants(source, 'drop', header):
        out.setdefault(family, []).append(text)
    return out


def test_the_index_load_is_staged_in_front_of_the_call():
    (child,) = by_family()[FAMILY_INDEX]
    assert '  s32 unlink_index_stage;' in child
    assert '  unlink_index_stage = *((s8 *) (rec + 0x182));\n  unlink(rec, gTracks[row], gTracks[unlink_index_stage]);' in child
    assert 'gTracks_base' not in child


def test_the_base_is_copied_for_a_call_that_indexes_one_table_twice():
    children = by_family()[FAMILY_BASE]
    assert len(children) == 1
    assert '  void * *gTracks_base;' in children[0] or '  void **gTracks_base;' in children[0].replace('void * *', 'void **')
    assert '  gTracks_base = gTracks;\n  unlink(rec, gTracks_base[row], gTracks_base[*((s8 *) (rec + 0x182))]);' in children[0]
    assert 'unlink(rec, gTracks[row], rec);' in children[0]


def test_both_at_once_puts_the_base_first_and_keeps_the_other_call():
    (child,) = by_family()[FAMILY_BOTH]
    first = child.index('gTracks_base = gTracks;')
    second = child.index('unlink_index_stage = *((s8 *)')
    assert first < second < child.index('unlink(rec, gTracks_base[row], gTracks_base[unlink_index_stage]);')
    assert 'unlink(rec, gTracks[row], rec);' in child


def test_an_impure_argument_or_a_volatile_table_blocks_the_staging():
    impure = SOURCE.replace('gTracks[row], gTracks[*', 'gTracks[row++], gTracks[*')
    assert not by_family(impure)
    assert not by_family(SOURCE.replace('extern void *gTracks[];', 'extern volatile void *gTracks[];'))


def test_a_header_table_counts_and_the_registry_runs_the_module():
    header = 'extern void *gTracks[];\n'
    assert FAMILY_BOTH in by_family(SOURCE.replace(header, ''), header)
    names = {family for rep in registry.declared() for family in rep.families}
    assert {FAMILY_INDEX, FAMILY_BASE, FAMILY_BOTH} <= names
