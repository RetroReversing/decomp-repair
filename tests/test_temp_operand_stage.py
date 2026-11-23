"""A temporary that holds `w & M` for one use, written to hold `w` with the mask at the use."""
from decomprepair import temp_operand_stage as t

SOURCE = '''void f(u32 *p, s32 k)
{
    s32 lo;
    s16 v;
    u32 w;

    lo = k;
    g(lo);
    w = *p;
    lo = (w & 0xFF); v = lo - 0x10;
    if (v <= 0)
    {
        return;
    }
    *p = w | v;
}
'''


def test_the_word_is_held_and_the_mask_moves_to_the_use():
    # An effect spawner's fade-out case (KMC GCC 2.7.2): 95 -> 85, `andi $v0, $v1, 0xFF` tied to the subtraction.
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert len(out) == 1 and 'lo = w; v = ((lo & 0xFF)) - 0x10;' in out[0]


def test_left_alone_when_the_temporary_is_read_later():
    later = SOURCE.replace('*p = w | v;', '*p = w | v | lo;')
    assert t.variants(later, 'f') == []
    reassigned = SOURCE.replace('*p = w | v;', 'lo = 3;\n    *p = w | v | lo;')
    assert len(t.variants(reassigned, 'f')) == 1


def test_it_declares_itself():
    from decomprepair import registry
    assert any(r.module == 'temp_operand_stage' for r in registry.declared())
