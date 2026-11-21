"""A case temporary split per case and its flag update folded, judged as one child."""
from decomprepair import case_split_combinations as c

DRAFT = '''extern u8 G;
extern u8 H;
void f(s32 k) {
    u8 *m;
    u8 a;
    u8 b;
    switch (k) {
    case 0:
        m = &H;
        a = *m;
        b = G;
        a |= 1;
        b |= 1;
        *m = a;
        G = b;
        g(m);
        break;
    case 1:
        m = &G;
        a = *m;
        b = H;
        a &= 0xFE;
        b &= 0xFE;
        *m = a;
        H = b;
        break;
    }
}
'''


def test_the_split_and_the_fold_come_as_one_child():
    out = [text for family, text in c.variants(DRAFT, 'f')]
    assert out and all(family == c.FAMILY for family, _ in c.variants(DRAFT, 'f'))
    assert any('m_0 = &H;' in text and '*m_0 |= 1;' in text and 'H &= 0xFE;' in text for text in out)
    # neither family alone gives that child
    from decomprepair import case_temporary_repairs, compound_global_update_repairs
    alone = [t for _, t in case_temporary_repairs.variants(DRAFT, 'f') + compound_global_update_repairs.variants(DRAFT, 'f')]
    assert not any('*m_0 |= 1;' in text for text in alone)

def test_nothing_without_a_switch():
    assert c.variants('void f(void) { g(); }\n', 'f') == []
