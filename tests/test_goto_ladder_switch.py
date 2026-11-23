"""m2c's goto ladder over one variable, as the switch it came from."""
from decomprepair import goto_ladder_switch as t

# A small ladder of the shape an N64 function had (141 instructions, 660 -> 0 with the switch below): a flag for "no
# case", shared tail blocks, an inline assignment, and a temporary a shared compare reads.
SOURCE = '''s32 f(s32 *o, s32 id) {
    s32 other = 1;

    if (o[0] & 1) {
        s32 last;
        other = 0;
        if (id == 0x153) goto to2FC;
        if (id < 0x154) {
            if (id == 7) goto to2FB;
            if (id < 8) {
                if (id == 2) id = 0x2FA;
                else other = 1;
                goto joined;
            }
            last = 0x10B;
            goto check;
        }
        if (id == 0x2A9) goto to302;
        last = 0x46D;
    check:
        if (id == last) {
            id = 0x2FC;
            goto joined;
        }
        other = 1;
        goto joined;
    to2FC: id = 0x2FC; goto joined;
    to2FB: id = 0x2FB; goto joined;
    to302: id = 0x302;
    }
joined:
    if (other) {
        id += 1;
    }
    return id;
}
'''


def test_the_ladder_becomes_a_switch():
    out = t.variants(SOURCE, 'f')
    assert out and all(family == t.FAMILY for family, _ in out)
    first = out[0][1]
    assert 'switch (id) {' in first and 'goto' not in first and 'last' not in first
    assert first.index('default:') < first.index('case 2:')  # the default first, as the compiler's layout needed
    assert 'case 0x10B:\n' in first and 'case 0x46D:\n' in first and 'case 0x153:\n' in first
    # the cases of one effect share an arm; the flag is set once, before the switch, and only the default changes it
    assert first.count('id = 0x2FC;') == 1
    body = first[first.index('switch'):]
    assert first.count('other = 0;') == 1 and body.count('other = 1;') == 1
    assert 'case 2:\n            id = 0x2FA;\n            break;' in first
    assert first.rstrip().endswith('return id;\n}')
    # the same values with the default last, and the groups in ascending order, are the other children
    assert any(text.index('default:') > text.index('case 2:') for _, text in out)
    assert len({text for _, text in out}) == len(out)


def test_the_effects_are_the_ladders_own():
    first = t.variants(SOURCE, 'f')[0][1]
    for value, result in ((2, 0x2FA), (7, 0x2FB), (0x153, 0x2FC), (0x10B, 0x2FC), (0x46D, 0x2FC), (0x2A9, 0x302)):
        assert f'case {t._hex(value)}:' in first
        assert f'id = {t._hex(result)};' in first
    assert 'case 0x2A8:' not in first and 'case 0x2AA:' not in first


def test_left_alone_otherwise():
    def none(source):
        return t.variants(source, 'f') == []
    assert none(SOURCE.replace('goto to2FC;', 'return 1;'))  # a return the switch cannot carry
    assert none(SOURCE.replace('goto joined;\n        }', 'goto elsewhere;\n        }'))  # leaves anywhere but after the block
    assert none(SOURCE.replace('if (id < 8)', 'if (o[1] < 8)'))  # a second tested variable
    assert none(SOURCE.replace('if (id == 0x153) goto to2FC;', 'if (id >= 0x153) goto to2FC;'))  # a range wider than the limit


def test_the_app_reaches_it():
    from decomprepair import registry
    assert any(r.module == 'goto_ladder_switch' for r in registry.declared())
