"""A call whose argument is a `?:`, made in each arm of an `if`/`else`."""
from decomprepair import registry
from decomprepair import ternary_call_arms as p

SOURCE = '''typedef struct { unsigned int w0, w1; } Gfx;
Gfx *load(Gfx *, int);
extern unsigned char *CMDS;

Gfx *run(Gfx *gfx)
{
    unsigned char *cmd;
    unsigned char *op;
    int n;

    cmd = CMDS;
    op = cmd;
    n = cmd[1] & 0x3F;
    gfx = load(gfx, (op[1] & 0xC0) ? 1 : 0);
    cmd += 2;
    gfx->w0 = n;
    return gfx;
}
'''


def texts(source):
    return [text for _, text in p.variants(source, 'run')]


def test_the_call_is_made_in_each_arm():
    want = ('    if (op[1] & 0xC0) {\n        gfx = load(gfx, 1);\n    } else {\n        gfx = load(gfx, 0);\n    }\n'
            '    cmd += 2;\n')
    assert any(want in text for text in texts(SOURCE))


def test_the_next_independent_statement_moves_above_the_split():
    """The 618-instruction display-list interpreter's step (SN64 GCC 2.8.1): 9751 -> 9486; the split alone 10446."""
    want = ('    n = cmd[1] & 0x3F;\n    cmd += 2;\n    if (op[1] & 0xC0) {\n        gfx = load(gfx, 1);\n    } else {\n'
            '        gfx = load(gfx, 0);\n    }\n    gfx->w0 = n;\n')
    assert any(want in text for text in texts(SOURCE))


def test_the_negated_order_is_offered_and_a_dependent_statement_stays():
    out = texts(SOURCE)
    assert any('if (!(op[1] & 0xC0)) {\n        gfx = load(gfx, 0);' in text for text in out)
    source = SOURCE.replace('    cmd += 2;\n', '    op += 2;\n')
    assert all('    op += 2;\n    if (' not in text for text in texts(source))


def test_no_ternary_or_a_call_in_the_condition_is_left_alone():
    assert texts(SOURCE.replace('(op[1] & 0xC0) ? 1 : 0', 'op[1] & 0xC0')) == []
    assert texts(SOURCE.replace('(op[1] & 0xC0) ? 1 : 0', 'pick(op) ? 1 : 0')) == []


def test_they_are_declared():
    assert registry.problems(next(r for r in registry.declared() if r.module == 'ternary_call_arms')) == []
