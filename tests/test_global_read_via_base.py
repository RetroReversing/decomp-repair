from decomprepair import registry
from decomprepair.global_read_via_base import FAMILY, REPAIR, variants

SOURCE = """extern int D_800AD200;
extern char D_800AD1E4[];
void f(void *arg0) {
    s32 a;
    s32 b;
    a = osVirtualToPhysical(D_800AD200);
    *(s32 *)((s8 *)D_800AD1E4 + 0) = 1;
    b = osVirtualToPhysical(D_800AD200) - a;
    g(&D_800AD200, b);
}
"""


def _children(source=SOURCE, header=''):
    return [text for family, text in variants(source, 'f', header) if family == FAMILY]


def test_each_read_and_then_all_reads_go_through_the_nearer_base():
    kids = _children()
    assert len(kids) == 3
    spelled = '(*(int *)((s8 *)D_800AD1E4 + 0x1C))'
    assert kids[0].count(spelled) == 1 and 'osVirtualToPhysical(D_800AD200) - a' in kids[0]
    assert kids[1].count(spelled) == 1 and 'a = osVirtualToPhysical(D_800AD200)' in kids[1]
    assert kids[2].count(spelled) == 2
    assert all('&D_800AD200' in kid for kid in kids)  # the address use stays


def test_a_scalar_base_is_addressed_and_the_header_may_declare_it():
    source = SOURCE.replace('extern char D_800AD1E4[];\n', '')
    kids = _children(source, 'extern s32 D_800AD1E4;\n')
    assert '(s8 *)&D_800AD1E4 + 0x1C' in kids[0]


def test_nothing_without_a_base_below_within_reach_or_for_a_non_scalar():
    assert _children(SOURCE.replace('D_800AD1E4', 'D_800AD000')) == []
    assert _children(SOURCE.replace('D_800AD1E4', 'D_800AD300')) == []
    assert _children(SOURCE.replace('extern int D_800AD200;', 'extern char D_800AD200[];')) == []
    assert _children(SOURCE.replace('D_800AD1E4', 'gList')) == []


def test_it_is_declared_for_the_callers():
    assert registry.problems(registry.get('global_read_via_base')) == []
    assert FAMILY in REPAIR['families']
