"""A store reading two array elements gets them through block-scoped temporaries first."""
from decomprepair import registry
from decomprepair.store_operand_temps import FAMILY, variants

FILL = '''void f(u16 *sb, u32 *sym, u32 *len, u32 y, u32 k) {
    do {
        sb[y] = (sym[k] << 7) + len[k];
        y += 1 << len[k];
    } while ((y >> 3) == 0);
}
'''


def test_the_elements_are_loaded_first():
    # a 681-instruction N64 decoder: the fill loop's block-local registers became the target's
    kids = variants(FILL, 'f')
    assert kids and {family for family, _ in kids} == {FAMILY}
    assert '{ __typeof__(sym[k]) t0 = sym[k], t1 = len[k]; sb[y] = (t0 << 7) + t1; }' in kids[0][1]
    assert 't0 = len[k], t1 = sym[k]; sb[y] = (t1 << 7) + t0;' in kids[1][1]


def test_one_element_or_a_call_stays():
    assert variants(FILL.replace('+ len[k]', '+ 3'), 'f') == []
    assert variants(FILL.replace('+ len[k];', '+ g(len[k]);'), 'f') == []


def test_the_module_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'store_operand_temps')
    assert registry.problems(repair) == [] and FAMILY in repair.families
