from decomprepair import initializer_single_use_inline as repair
from decomprepair import registry

HEADER = 'typedef struct { short ob[3]; short flag; } Vtx;\nextern s32 gCount;\nextern Vtx *gDots;\n'
SOURCE = '''void f(Vtx **out) {
    Vtx *vtx;

    {
        s32 base = gCount;

        vtx = &gDots[base];
    }
    *out = vtx;
}
'''


def children(source, header=HEADER):
    return [text for _, text in repair.variants(source, 'f', header)]


def test_one_read_global_moves_into_the_subscript():
    [child] = children(SOURCE)
    assert 'vtx = &gDots[gCount];' in child
    assert 'base' not in child


def test_conversion_is_kept_as_a_cast():
    [child] = children(SOURCE.replace('s32 base', 'u8 base'))
    assert 'vtx = &gDots[(u8) gCount];' in child


def test_unknown_global_type_keeps_the_local_type():
    [child] = children(SOURCE, header='')
    assert '[(s32) gCount]' in child


def test_expression_is_parenthesised():
    source = 'int f(int a) {\n    int t = a + 1;\n    return t * 2;\n}\n'
    [child] = children(source, header='')
    assert 'return ((int) (a + 1)) * 2;' in child


def test_refuses_two_reads_calls_and_changes():
    two = SOURCE.replace('*out = vtx;', '').replace('&gDots[base];', '&gDots[base + base];')
    assert not children(two)
    assert not children(SOURCE.replace('= gCount;', '= next();'))
    assert not children(SOURCE.replace('vtx = &gDots[base];', 'vtx = find(base);'))
    assert not children(SOURCE.replace('vtx = &gDots[base];', 'vtx = &gDots[base++];'))
    assert not children(SOURCE.replace('vtx = &gDots[base];', 'gCount = 0;\n        vtx = &gDots[base];'))
    assert not children(SOURCE.replace('vtx = &gDots[base];', 'if (base) vtx = gDots;'))


def test_registered():
    assert any(item.module == 'initializer_single_use_inline' for item in registry.declared())


def test_casts_are_not_calls():
    source = SOURCE.replace('&gDots[base];', '&((Vtx *) gDots)[base];')
    assert 'vtx = &((Vtx *) gDots)[gCount];' in children(source)[0]
    assert not children(SOURCE.replace('vtx = &gDots[base];', 'vtx = find (base);'))


def test_only_a_volatile_it_reads_refuses():
    assert children(SOURCE, HEADER + 'extern volatile s32 gRegister;\n')
    assert not children(SOURCE, HEADER.replace('extern s32 gCount;', 'extern volatile s32 gCount;'))
