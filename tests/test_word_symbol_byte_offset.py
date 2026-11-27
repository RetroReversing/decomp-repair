from decomprepair.word_symbol_byte_offset import variants

SOURCE = '''extern s32 D_A;
extern M2C_UNK D_B;
void f(s32 i)
{
    void *p;
    void *q;
    q = *((&D_A) + i);
    p = i + (&D_B);
    g(q, p, &D_A);
}
'''


def sources(source):
    return [child for _, child in variants(source, 'f')]


def test_writes_both_symbols_as_bytes_then_each():
    both, first, second = sources(SOURCE)
    assert 'q = *(s32 *)(((u8 *)&D_A) + i);' in both
    assert 'p = i + ((u8 *)&D_B);' in both
    assert 'g(q, p, &D_A);' in both
    assert 'p = i + (&D_B);' in first
    assert 'q = *((&D_A) + i);' in second


def test_leaves_arrays_casts_and_arguments():
    assert not sources(SOURCE.replace('extern s32 D_A;', 'extern s32 D_A[];').replace('i + (&D_B)', 'i'))
    assert not sources('extern s32 D_A;\nvoid f(s32 i)\n{\n    g((u8 *)&D_A + i, &D_A);\n}\n')
    assert not sources(sources(SOURCE)[0])
