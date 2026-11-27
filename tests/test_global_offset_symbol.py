from decomprepair import registry
from decomprepair.global_offset_symbol import FAMILY, REPAIR, variants

SOURCE = """extern s32 D_800B84B8;
extern s32 D_800B84F0;

void f(void) {
    if ((*(s16 *)((s8 *)&D_800B84B8 + 2)) != 0) {
        return;
    }
    (*(s16 *)((s8 *)&D_800B84B8 + 2)) = (s16) ((u16) (*(s16 *)((s8 *)&D_800B84B8 + 2)) + 1);
    g(&D_800B84F0);
}
"""


def _children(source=SOURCE, header=''):
    return [text for family, text in variants(source, 'f', header) if family == FAMILY]


def test_the_offset_reads_become_the_global_at_that_address_with_its_extern():
    kids = _children()
    assert len(kids) == 4  # all three uses together, then each alone
    assert kids[0].count('D_800B84BA') == 4  # three uses and the extern
    assert 'extern s16 D_800B84BA;\n\nvoid f' not in kids[0]  # declared before the signature line
    assert 'extern s16 D_800B84BA;\nvoid f(void) {' in kids[0]
    assert 'D_800B84BA = (s16) ((u16) D_800B84BA + 1);' in kids[0]
    assert '&D_800B84B8 + 2' not in kids[0]
    assert kids[1].count('(s8 *)&D_800B84B8 + 2') == 2 and 'extern s16 D_800B84BA;' in kids[1]


def test_an_array_base_a_field_macro_a_negative_offset_and_an_existing_declaration():
    source = SOURCE.replace('extern s32 D_800B84B8;', 'extern u8 D_800B84B8[];\nextern s16 D_800B84BA;')
    source = source.replace('&D_800B84B8', 'D_800B84B8')
    kids = _children(source)
    assert kids and 'extern s16 D_800B84BA;' in kids[0] and kids[0].count('extern s16 D_800B84BA;') == 1
    macro = 'extern s32 D_800B84BC;\nvoid f(void) { x = M2C_FIELD(&D_800B84BC, s16 *, -2); }\n'
    assert _children(macro)[0].count('D_800B84BA') == 2


def test_nothing_for_a_clashing_declaration_a_non_symbol_base_or_a_zero_offset():
    assert _children(SOURCE.replace('extern s32 D_800B84F0;', 'extern s32 D_800B84F0;\nextern u8 D_800B84BA;')) == []
    assert _children(SOURCE.replace('D_800B84B8', 'gCounter')) == []
    assert _children(SOURCE.replace('+ 2)', '+ 0)')) == []
    assert _children(SOURCE.replace('(s16 *)', '(f32 *)')) == []


def test_it_is_declared_for_the_callers():
    assert registry.problems(registry.get('global_offset_symbol')) == []
    assert FAMILY in REPAIR['families']
