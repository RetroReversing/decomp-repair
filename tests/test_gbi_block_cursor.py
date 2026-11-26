"""Display-list commands written through a block-scoped cursor copy, as the Gbi macros expand."""
from decomprepair import gbi_block_cursor as p
from decomprepair import registry

SOURCE = '''typedef struct { unsigned int w0, w1; } Gfx;
Gfx *flush(Gfx *);

Gfx *build(Gfx *gfx, unsigned char *cmd, int n)
{
    Gfx *dl;
    int b;

    gfx->w0 = 0xE2001E01;
    gfx->w1 = 1;
    gfx++;
    gfx->w0 = 0xE7000000;
    gfx->w1 = 0;
    gfx++;
    while (n--) {
        switch (*cmd) {
        case 2:
            dl = gfx++;
            b = cmd[1] << 1;
            dl->w0 = b | 0x02100000;
            dl->w1 = cmd[2];
            cmd += 6;
            break;
        default:
            dl = gfx++;
            dl->w0 = 0xDF000000;
            dl->w1 = 0;
            return gfx;
        }
    }
    return flush(gfx);
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'build')]


def test_every_command_gets_its_own_block_pointer():
    """The 618-instruction display-list interpreter (SN64 GCC 2.8.1 -mfp32): 5566 -> 4241 with every site rewritten."""
    out = texts(SOURCE)
    first = out[0]
    assert ('    {\n        Gfx *_g = gfx++;\n        _g->w0 = 0xE2001E01;\n        _g->w1 = 1;\n    }\n'
            '    {\n        Gfx *_g = gfx++;\n        _g->w0 = 0xE7000000;\n') in first
    assert ('            {\n                Gfx *_g = gfx++;\n                b = cmd[1] << 1;\n'
            '                _g->w0 = b | 0x02100000;\n                _g->w1 = cmd[2];\n            }\n'
            '            cmd += 6;\n') in first
    assert '_g->w0 = 0xDF000000;\n                _g->w1 = 0;\n            }\n            return gfx;' in first
    assert 'dl->' not in first


def test_each_kind_alone_is_offered():
    out = texts(SOURCE)
    assert len(out) == 3
    assert 'gfx->w0 = 0xE2001E01;' in out[2] and 'dl->' not in out[2]
    assert 'gfx->w0 = 0xE2001E01;' not in out[1] and 'dl->w0 = b' in out[1]


def test_a_pointer_read_later_is_left_alone():
    source = SOURCE.replace('            dl->w1 = 0;\n            return gfx;', '            dl->w1 = 0;\n            return dl;')
    assert all('_g->w0 = 0xDF000000' not in text for text in texts(source))


def test_it_is_declared():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'gbi_block_cursor')) == []
