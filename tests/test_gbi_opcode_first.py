"""A display-list word whose opcode constant is written last, written first as the Gbi macro writes it."""
from decomprepair import gbi_opcode_first as p
from decomprepair import registry

SOURCE = '''typedef struct { unsigned int w0, w1; } Gfx;

void put(Gfx *g, int n, int v, int b)
{
    g->w0 = (n << 12) | (((v + n) & 0x7F) << 1) | 0x01000000;
    g->w1 = b;
    g[1].w0 = b | 0x02140000;
    g[1].w1 = b | 0x10;
    if (n == 1 || v) {
        g[2].w0 = 0;
    }
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'put')]


def test_the_vertex_word_gets_its_opcode_first():
    """The 618-instruction display-list interpreter (SN64 GCC 2.8.1 -mfp32): 4226 -> 4001."""
    out = texts(SOURCE)
    assert any('g->w0 = 0x01000000 | (n << 12) | (((v + n) & 0x7F) << 1);\n    g->w1 = b;\n    g[1].w0 = b | 0x02140000;'
               in text for text in out)


def test_each_site_and_all_of_them():
    out = texts(SOURCE)
    assert len(out) == 3
    assert 'g[1].w0 = 0x02140000 | b;' in out[-1] and 'g->w0 = 0x01000000 |' in out[-1]
    assert all('g[1].w1 = b | 0x10;' in text for text in out)


def test_small_constants_and_logical_ors_are_left_alone():
    source = SOURCE.replace('0x01000000', '0x10000').replace('0x02140000', '0xFF')
    assert texts(source) == []


def test_it_is_declared():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'gbi_opcode_first')) == []
