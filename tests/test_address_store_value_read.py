"""A stored `(s32)&D` where the target loads the word (a free-list push on a KMC GCC 2.7.2 object allocator)."""
from decomprepair import registry
from decomprepair.address_store_value_read import FAMILY, variants

SOURCE = """extern s32 D_800B2FE0;
extern char D_802028E0[];
s32 push(s32 off) {
    *(s32 *)(D_802028E0 + off) = (s32)&D_800B2FE0;
    return 0;
}
"""


def test_the_word_is_stored_not_its_address():
    (family, child), = variants(SOURCE, 'push', '')
    assert family == FAMILY
    assert '(D_802028E0 + off) = D_800B2FE0;' in child


def test_a_bare_address_and_a_header_declaration():
    source = SOURCE.replace('(s32)&', '&').replace('extern s32 D_800B2FE0;\n', '')
    assert not variants(source, 'push', '')
    (_, child), = variants(source, 'push', 'extern u32 D_800B2FE0;')
    assert '= D_800B2FE0;' in child


def test_arrays_pointers_and_narrow_globals_keep_their_address():
    for decl in ('extern u8 D_800B2FE0[];', 'extern s32 *D_800B2FE0;', 'extern u16 D_800B2FE0;'):
        assert not variants(SOURCE.replace('extern s32 D_800B2FE0;', decl), 'push', '')


def test_one_child_each_and_all_together():
    two = SOURCE.replace('    return 0;', '    *(s32 *)(D_802028E0 + 4) = (s32)&D_800B2FE0;\n    return 0;')
    kids = variants(two, 'push', '')
    assert len(kids) == 3 and kids[-1][1].count('&D_800B2FE0') == 0


def test_a_comparison_or_a_use_elsewhere_is_left_alone():
    assert not variants(SOURCE.replace(' = (s32)&D_800B2FE0;', ' == (s32)&D_800B2FE0;'), 'push', '')
    assert not variants(SOURCE.replace('(s32)&D_800B2FE0;', '(s32)&D_800B2FE0 + 4;'), 'push', '')


def test_it_declares_itself():
    assert any(FAMILY in r.families for r in registry.declared())
