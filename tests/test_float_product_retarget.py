from decomprepair import float_product_retarget as retarget

SOURCE = '''f32 near(f32 limit)
{
    f32 dist;
    f32 weight;
    f32 best;
    s32 i;

    best = limit;
    for (i = 0; i < 4; i++)
    {
        dist = measure(i) * weight;
        if (dist < best)
        {
            best = dist;
        }
    }
    i = 0;
    do
    {
        weight = 1.0f;
        if (kind(i) == 3)
        {
            weight = scale(i);
        }
        if (ok(i))
        {
            weight = approx(i) * weight;
            if (weight < best)
            {
                best = weight;
                pick = i;
            }
        }
        i += 1;
    }
    while (i < 4);
    return best;
}
'''


def test_the_product_goes_to_a_float_that_is_free_there():
    out = [text for _, text in retarget.variants(SOURCE, 'near')]
    assert out
    text = out[0]
    assert 'dist = approx(i) * weight;' in text
    assert 'if (dist < best)\n            {\n                best = dist;' in text
    assert 'weight = 1.0f;' in text and 'weight = scale(i);' in text
    assert text.count('{') == text.count('}')


def test_a_float_the_loop_mentions_or_a_value_read_after_the_loop_is_left_alone():
    assert not retarget.variants(SOURCE.replace('weight = 1.0f;', 'weight = 1.0f;\n        dist = 0.0f;'), 'near')
    assert not retarget.variants(SOURCE.replace('return best;', 'return weight;'), 'near')
    assert not retarget.variants(SOURCE.replace('weight = approx(i) * weight;', 'weight = weight * 2.0f;'), 'near')


def test_the_module_declares_itself_to_the_registry():
    from decomprepair import registry
    declared = {r.module: r for r in registry.declared()}
    assert 'float_product_retarget' in declared and not registry.problems(declared['float_product_retarget'])
