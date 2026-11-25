from decomprepair import compare_load_weight as cw

SOURCE = """\
extern s32 D_MODE;
f32 dist(void *);
void tick(void *o, s32 k)
{
    f32 d;
    d = dist(o);
    if (D_MODE == 1) {
        if (d < 500.0f) {
            hit(o);
        }
    } else if (k == 2) {
        miss(o);
    }
}
"""


def test_the_compared_global_is_loaded_in_a_two_deep_scope_first():
    family, text = cw.variants(SOURCE, 'tick')[0]
    assert family == 'compare_load_weight'
    assert '__typeof__(D_MODE) mode;' in text
    assert 'do { do { mode = D_MODE; } while (0); } while (0);\n    if (mode == 1) {' in text
    assert '} else if (k == 2) {' in text


def test_depths_one_and_three_follow():
    texts = [t for _, t in cw.variants(SOURCE, 'tick')]
    assert len(texts) == 3
    assert 'do { mode = D_MODE; } while (0);\n' in texts[1]
    assert 'do { do { do { mode = D_MODE; } while (0); } while (0); } while (0);' in texts[2]


def test_locals_parameters_and_else_if_are_left_alone():
    assert cw.variants(SOURCE.replace('if (D_MODE == 1)', 'if (k == 1)'), 'tick') == []
    local = SOURCE.replace('    f32 d;\n', '    f32 d;\n    s32 D_MODE;\n')
    assert cw.variants(local, 'tick') == []
    chained = SOURCE.replace('    if (D_MODE == 1) {', '    if (k) {\n    } else if (D_MODE == 1) {')
    assert cw.variants(chained, 'tick') == []
