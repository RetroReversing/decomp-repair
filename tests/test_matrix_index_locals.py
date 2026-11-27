from decomprepair.matrix_index_locals import COL, ROW, variants

SOURCE = '''extern u8 T[][24];
void f(u8 i, u8 *out)
{
    u8 n;
    n = T[rec[i].d][rec[i].c];
    *out = n;
}
'''

POINTER = '''void f(s32 i, u8 *out)
{
    s32 n;
    n = *((((*(D_B + (i * 5))) * 0x18) + D_T) + (*(D_C + (i * 5))));
    *out = n;
}
'''


def sources(source):
    return [child for _, child in variants(source, 'f')]


def test_stages_column_before_row():
    first, second = sources(SOURCE)
    assert f'{COL} = rec[i].c;\n    {ROW} = rec[i].d;\n    n = T[{ROW}][{COL}];' in first
    assert f'{ROW} = rec[i].d;\n    {COL} = rec[i].c;\n    n = T[{ROW}][{COL}];' in second
    assert f's32 {ROW};' in first and f's32 {COL};' in first


def test_stages_the_pointer_spelling():
    first = sources(POINTER)[0]
    assert f'{COL} = *(D_C + (i * 5));\n    {ROW} = *(D_B + (i * 5));' in first
    assert f'n = *(((({ROW}) * 0x18) + D_T) + ({COL}));' in first


def test_leaves_other_reads():
    assert not sources(SOURCE.replace('rec[i].d', 'i'))
    assert not sources(SOURCE.replace('rec[i].d', 'g(rec[i].d)'))
    assert not sources(SOURCE.replace('n = T', 'T').replace('][rec[i].c];', '][rec[i].c] = 0;'))
    assert not sources(sources(SOURCE)[0])
