"""A right shift of a u16 variable masked to the bits it can have."""
from decomprepair import registry
from decomprepair.narrow_shift_mask import FAMILY, variants

FILL = '''void f(u16 *tab, u32 a, u32 t5, u32 y) {
    u16 ent;
    ent = tab[a];
    tab[(ent >> 7) + t5 + y] = 1;
}
'''


def test_the_shift_is_masked():
    # a 681-instruction N64 decoder: (ent >> 7) & 0x1FF lengthened a copy's life with no code change
    kids = variants(FILL, 'f')
    assert [family for family, _ in kids] == [FAMILY]
    assert 'tab[((ent >> 7) & 0x1FF) + t5 + y] = 1;' in kids[0][1]


def test_a_wide_or_masked_value_stays():
    assert variants(FILL.replace('u16 ent;', 'u32 ent;'), 'f') == []
    assert variants(FILL.replace('(ent >> 7) + t5', '(ent >> 7) & 3'), 'f') == []


def test_the_module_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'narrow_shift_mask')
    assert registry.problems(repair) == [] and FAMILY in repair.families
