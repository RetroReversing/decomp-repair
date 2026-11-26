"""Block-scoped pointers of several switch arms written as one function-level local."""
from decomprepair import block_local_share as m

SOURCE = '''Gfx *f(u8 *cmd, Gfx *gfx)
{
    s32 n;
    for (;;) {
        switch (*cmd) {
        case 1:
            {
                Gfx *_g = gfx++;
                _g->w0 = 1;
            }
            break;
        case 2:
            {
                Gfx *_g = gfx++;
                _g->w0 = cmd[1];
            }
            break;
        case 3:
            {
                Gfx *_g = gfx++;
                n = cmd[2];
                _g->w0 = n;
            }
            break;
        default:
            return gfx;
        }
    }
}
'''


def test_neighbouring_arms_share_one_pointer():
    # An SN GCC 2.8.1 model loader's two gSPModifyVertex arms sharing one pointer: 1335 -> 825, the first arm's tail
    # cross-jumped into the second's as in the target.
    found = m.variants(SOURCE, 'f')
    assert [family for family, _ in found] == ['block_local_share'] * 3
    every, first, second = (text for _, text in found)
    assert every.startswith('Gfx *f(u8 *cmd, Gfx *gfx)\n{\n    Gfx *_g;\n    s32 n;')
    assert every.count('Gfx *_g = gfx++;') == 0 and every.count('_g = gfx++;') == 3
    assert first.count('Gfx *_g = gfx++;') == 1 and 'case 3:\n            {\n                Gfx *_g = gfx++;' in first
    assert second.count('Gfx *_g = gfx++;') == 1 and 'case 1:\n            {\n                Gfx *_g = gfx++;' in second


def test_left_alone_otherwise():
    # one block only, the name used outside the blocks, its address taken, a non-scalar value
    one = SOURCE.replace('                Gfx *_g = gfx++;\n                _g->w0 = cmd[1];', '                gfx->w0 = 2;')
    one = one.replace('                Gfx *_g = gfx++;\n                n = cmd[2];', '                n = cmd[2];')
    assert m.variants(one.replace('_g->w0 = n;', 'gfx->w0 = n;'), 'f') == []
    assert m.variants(SOURCE.replace('return gfx;', 'return _g;'), 'f') == []
    assert m.variants(SOURCE.replace('_g->w0 = 1;', 'h(&_g);'), 'f') == []
    assert m.variants(SOURCE.replace('Gfx *_g = gfx++;', 'Gfx _g = *gfx;').replace('_g->', '_g.'), 'f') == []
