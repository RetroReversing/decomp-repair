"""gDPSetTile words with the clamp fields as zero-valued locals, as the SDK macros spell them."""
from decomprepair import registry
from decomprepair import settile_clamp_locals as p

SOURCE = '''typedef struct { unsigned int w0, w1; } Gfx;

#define G(gfx, a, b) { Gfx *_g = (gfx)++; _g->w0 = (a); _g->w1 = (b); }

Gfx *load(Gfx *gfx, int ws, int ts, int n)
{
    int i;
    int fmt;

    fmt = n;
    G(gfx, 0xFD100000, n);
    G(gfx, 0xF5100000, 0x07000000 | ((ts & 0xF) << 14) | ((ws & 0xF) << 4));
    G(gfx, 0xE6000000, 0);
    G(gfx, 0xF5100000 | (((n + 7) >> 3) << 9), ((ts & 0xF) << 14) | (0x01000000 | ((ws & 0xF) << 4)));
    for (i = 0; i < 4; i++) {
        G(gfx, 0xF5000000 | ((fmt & 7) << 21), ((i & 7) << 24) | ((ws & 0xF) << 14) | ((i & 0xF) << 10) | ((ts & 0xF) << 4) | (i & 0xF));
    }
    gfx->w0 = 0xF5400000;
    gfx->w1 = ((ts & 0xF) << 14) | ((ws & 0xF) << 4);
    return gfx;
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'load')]


def test_every_settile_word_gets_the_clamp_fields_and_the_locals_are_set_first():
    """A 606-instruction texture loader (SN64 GCC 2.8.1): 7042 -> 0 with every SetTile word and `cmt = cms = 0;` first."""
    out = texts(SOURCE)
    assert len(out) == 2
    text = out[0]
    assert '    int fmt;\n\n    s32 cms;\n    s32 cmt;\n\n    cmt = cms = 0;\n    fmt = n;' in text
    assert ('G(gfx, 0xF5100000, 0x07000000 | ((cmt & 3) << 18) | ((ts & 0xF) << 14) | ((cms & 3) << 8) | '
            '((ws & 0xF) << 4));') in text
    assert ('((cmt & 3) << 18) | ((ts & 0xF) << 14) | (0x01000000 | ((cms & 3) << 8) | ((ws & 0xF) << 4))') in text
    assert ('((i & 7) << 24) | ((cmt & 3) << 18) | ((ws & 0xF) << 14) | ((i & 0xF) << 10) | ((cms & 3) << 8) | '
            '((ts & 0xF) << 4) | (i & 0xF)') in text
    assert 'gfx->w1 = ((cmt & 3) << 18) | ((ts & 0xF) << 14) | ((cms & 3) << 8) | ((ws & 0xF) << 4);' in text
    assert 'G(gfx, 0xE6000000, 0);' in text and 'G(gfx, 0xFD100000, n);' in text
    assert 'cms = cmt = 0;' in out[1]


def test_functions_that_name_the_fields_or_have_no_settile_are_left_alone():
    assert texts(SOURCE.replace('int fmt;', 'int fmt;\n    int cms;')) == []
    assert texts(SOURCE.replace('0xF5', '0xF6')) == []
    assert texts(SOURCE.replace('<< 14)', '<< 13)')) == []


def test_the_module_is_declared():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'settile_clamp_locals')) == []
