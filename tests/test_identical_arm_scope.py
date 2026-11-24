"""identical_arm_scope: equal arms written once inside `do { } while (0)` (a KMC GCC 2.7.2 collision routine: the plain
collapse 7266 -> 8383, the scoped one 7266 -> 7009). The source below is made up; it only has that shape."""
from decomprepair import identical_arm_scope as scope
from decomprepair import registry

SOURCE = """f32 f(f32 *p, f32 y, f32 a7, void *v) {
    f32 t;
    if (v) { t = y + a7; } else { t = y + a7; }
    if (t < *p) { *p = t; }
    return t;
}
"""


def test_the_arm_goes_into_a_one_shot_scope():
    [(family, text)] = scope.variants(SOURCE, 'f')
    assert family == 'identical_arm_scope'
    assert 'do { t = y + a7; } while (0);' in text and 'if (v)' not in text and 'else' not in text


def test_different_arms_or_a_call_in_the_condition_stay():
    assert not scope.variants(SOURCE.replace('} else { t = y + a7; }', '} else { t = y - a7; }'), 'f')
    assert not scope.variants(SOURCE.replace('if (v)', 'if (g(v))'), 'f')


def test_it_is_declared_in_the_registry():
    assert 'identical_arm_scope' in {r.module.rsplit('.', 1)[-1] for r in registry.declared()}
