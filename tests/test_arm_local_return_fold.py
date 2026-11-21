"""Chained zero stores, per-arm locals and the packed return, from one clamp function (525 -> 0)."""
from decomprepair import arm_local_return_fold as a

DRAFT = '''extern volatile f32 G0;
extern volatile f32 G1;
extern volatile f32 G2;
s32 f(void *p, f32 *q, s32 k) {
    f32 x;
    f32 y;
    f32 v;
    f32 d = *(f32 *) p;
    if (d == 0.0f) {
        G1 = (G0 = 0.0f);
    } else {
        x = (q[0] - d) / d;
        y = (q[1] - d) / d;
        G0 = x;
        G1 = y;
    }
    if (d == 1.0f) {
        v = 0.0f;
        G2 = 0.0f;
    } else {
        x = (q[2] - d) / d;
        v = q[3] / d;
        G2 = x;
    }
    y = G1;
    G2 = v;
    {
        s32 high = (0xFF << ((s32) G0)) & (0xFF >> (7 - ((s32) G1)));
        s32 low = (0xFF << ((s32) G2)) & (0xFF >> (7 - ((s32) y)));
        if (k) {
            return ((high & 0xFF) << 8) | (low & 0xFF);
        } else {
            return ((high & 0xFF) << 8) | (low & 0xFF);
        }
    }
}
'''


def test_chained_constant_store_is_two_stores():
    (_, text), = a.chain_variants(DRAFT, 'f')
    assert 'G0 = 0.0f;\n    G1 = 0.0f;' in text and '(G0 = ' not in text


def test_arm_locals_split_each_and_together():
    out = [t for _, t in a.arm_variants(DRAFT, 'f')]
    assert any('f32 x_arm;' in t and 'x_arm = (q[0]' in t and 'G0 = x_arm;' in t for t in out)
    assert any('f32 y_arm;' in t and 'G1 = y_arm;' in t for t in out)
    both = out[-1]
    assert 'x_arm' in both and 'y_arm' in both and 'v_arm' not in both  # v is read after the arms
    assert 'x = (q[2]' in both  # only the first arm is split


def test_return_collapse_and_packed_fold():
    (_, collapsed), = a.collapse_variants(DRAFT, 'f')
    assert 'if (k)' not in collapsed and collapsed.count('return') == 1
    out = [t for _, t in a.fold_variants(collapsed, 'f')]
    assert 'do { } while (0);\n        high = (high & 0xFF) << 8;\n        return high | (low & 0xFF);' in out[0]
    assert any('do { } while (0);' in t and 'high = ' not in t.split('do {')[1] for t in out)
    # offered as one child from the draft, too
    assert any('high = (high & 0xFF) << 8;' in t and 'if (k)' not in t for _, t in a.variants(DRAFT, 'f'))


def test_every_step_comes_as_one_child_first():
    (family, text), *_ = a.variants(DRAFT, 'f')
    assert family == a.FOLD
    assert 'G0 = 0.0f;\n    G1 = 0.0f;' in text and 'x_arm' in text and 'y_arm' in text
    assert 'if (k)' not in text and 'high = (high & 0xFF) << 8;' in text and 'do { } while (0);' in text


def test_nothing_to_do():
    assert a.variants('s32 f(void) { return 0; }', 'f') == []
    assert a.variants('s32 g(void) { return 0; }', 'f') == []
