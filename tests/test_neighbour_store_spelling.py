"""One store of a global spelled through its neighbour, to keep two branch ends apart."""
from decomprepair.neighbour_store_spelling import FAMILY, variants

SOURCE = '''extern s8 D_801C0022;
extern s8 D_801C0023;
extern s32 D_801C0024;
void f(s32 a) {
    if (a == 0) {
        D_801C0023 = -1;
        D_801C0022 = 0;
    } else {
        D_801C0023 = 1;
        D_801C0022 = 0;
    }
    D_801C0024 = a;
}
'''


def _kids(text, header=''):
    return [s for fam, s in variants(text, 'f', header) if fam == FAMILY]


def test_each_store_is_offered_through_its_neighbour_of_the_same_type():
    kids = _kids(SOURCE)
    assert SOURCE.replace('D_801C0023 = -1;', '(&D_801C0022)[1] = -1;') in kids
    assert SOURCE.replace('D_801C0022 = 0;', '(&D_801C0023)[-1] = 0;', 1) in kids
    assert len(kids) == 4
    assert not any('D_801C0024)' in k for k in kids)


def test_declarations_in_the_header_count():
    body = SOURCE[SOURCE.index('void'):]
    header = 'extern s8 D_801C0022;\nextern s8 D_801C0023;\n'
    assert len(_kids(body, header)) == 4


def test_a_comparison_or_a_member_store_is_not_a_store_of_the_global():
    text = '''extern s8 D_801C0022;
extern s8 D_801C0023;
void f(s32 *p) { if (D_801C0022 == D_801C0023) { *p = 0; } }
'''
    assert not _kids(text)
