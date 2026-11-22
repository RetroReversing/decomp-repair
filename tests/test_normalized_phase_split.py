from decomprepair import local_flow, phase_lifetime_repairs
from decomprepair.normalized_phase_split import CHAIN_FAMILY, FAMILY, normalize, variants

# A nested walk written the way a hand-edited best is: a list of declarators and a macro that reads a local.
SOURCE = """#define F(p, t, o) (*(t *)((s8 *)(p) + (o)))
#define NF ((found ^ 1) & 1)
extern void *g;
extern s32 probe(void *, void *);
void *walk(void *arg) {
    s32 found;
    void *cur, *child, *grand, *tmp;
    found = 0;
    cur = F(arg, void *, 0x20);
    F(cur, s32, 4) = 1;
    if (probe(cur, arg)) found = 1;
    child = F(cur, void *, 0x58);
    while ((child != NULL) & NF) {
        grand = F(child, void *, 8);
        F(grand, s32, 4) = 2;
        if (probe(grand, arg)) found = 1;
        child = F(child, void *, 0);
    }
    tmp = F(arg, void *, 0x40);
    F(tmp, s32, 4) = 4;
    tmp = F(arg, void *, 0x44);
    F(tmp, s32, 4) = 5;
    F(tmp, s32, 8) = 6;
    cur = F(arg, void *, 0x24);
    F(cur, s32, 8) = 3;
    return cur;
}
"""


def test_the_source_hides_its_phases_from_the_existing_split():
    assert phase_lifetime_repairs.splits(SOURCE, 'walk') == []


def test_normalize_writes_one_declarator_per_line_and_expands_the_macro():
    normal = normalize(SOURCE, 'walk')
    assert 'void *cur;\n    void *child;\n    void *grand;\n    void *tmp;' in normal
    assert '#define NF' not in normal and '((found ^ 1) & 1)' in normal
    assert local_flow.analyze(normal, 'walk') is not None


def test_a_proven_split_is_offered_once_the_source_is_normalized():
    singles = [text for family, text in variants(SOURCE, 'walk') if family == FAMILY]
    assert any('void *__repair_phase_cur;' in text and '__repair_phase_cur = F(arg, void *, 0x24);' in text
               for text in singles)
    assert any('__repair_phase_tmp = F(arg, void *, 0x44);' in text for text in singles)


def test_normalize_leaves_a_clean_source_alone():
    clean = normalize(SOURCE, 'walk')
    assert normalize(clean, 'walk') == clean
    assert all(family == CHAIN_FAMILY for family, _ in variants(clean, 'walk'))


def test_the_chain_applies_the_splits_one_after_another():
    chain = [text for family, text in variants(SOURCE, 'walk') if family == CHAIN_FAMILY][0]
    assert chain.count('void *__repair_phase_') >= 2
    assert local_flow.analyze(chain, 'walk') is not None


def test_a_macro_used_elsewhere_or_with_parameters_stays():
    source = SOURCE.replace('F(arg, void *, 0x24)', 'F(arg, void *, 0x24) /* NF */').replace(
        '#define NF ((found ^ 1) & 1)', '#define NF(x) ((found ^ x) & 1)').replace('& NF)', '& NF(1))')
    assert '#define NF(x)' in normalize(source, 'walk')
