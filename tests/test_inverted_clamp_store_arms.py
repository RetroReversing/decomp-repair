from decomprepair import registry
from decomprepair.inverted_clamp_store_arms import variants

SOURCE = """void f(u8 *p) {
    u32 t;
    u32 v;
    t = p[1] + p[2];
    if (t > 0xEA60U)
    {
      v = 0x75300000;
    }
    else
    {
      v = t << 0xF;
    }
    *((s32 *) (p + 0x28)) = v;
}
"""


def flat(text):
    return ' '.join(text.split())


def test_the_inverted_test_stores_in_each_arm():
    [(family, out)] = variants(SOURCE, 'f')
    assert family == 'inverted_clamp_store_arms'
    assert flat('if (t <= 0xEA60U) { *((s32 *) (p + 0x28)) = t << 0xF; } else { *((s32 *) (p + 0x28)) = 0x75300000; }') \
        in flat(out)
    assert '= v;' not in out


def test_a_value_read_later_is_left_alone():
    assert variants(SOURCE.replace('= v;\n}', '= v;\n    g(v);\n}'), 'f') == []


def test_declared():
    repair = registry.get('inverted_clamp_store_arms')
    assert repair is not None and not registry.problems(repair)
