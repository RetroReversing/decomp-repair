from decomprepair import float_literal_local_stage as repair

SOURCE = '''void f(f32 angle, int x) {
    f32 value;
    if (x) {
        value = (angle * 3.14f) / 180.0f;
    } else {
        value = (angle * 3.14f) / 180.0f;
    }
    consume(value);
}
'''


def test_stage_literal_in_each_arm_and_both_together():
    out = repair.variants(SOURCE, 'f')
    assert len(out) == 3
    assert out[-1][1].count('value = 3.14f;') == 2
    assert out[-1][1].count('(angle * value) / 180.0f') == 2


def test_rejects_aliases_and_volatile_float():
    assert not repair.variants(SOURCE.replace('consume(value);', 'consume(&value);'), 'f')
    assert not repair.variants(SOURCE.replace('angle * 3.14f', 'value * 3.14f'), 'f')
    assert not repair.variants(SOURCE, 'f', 'typedef volatile float f32;')
