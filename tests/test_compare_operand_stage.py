"""A float comparison's right operand staged in a local."""
from decomprepair import compare_operand_stage as stage

SOURCE = '''inline static f32 same(f32 v) { return v; }
s32 f(f32 *p, f32 *q) {
    f32 d1;
    d1 = p->x - q->x;
    if (d1 < (p->x - q->x)) {
        return 1;
    }
    if (d1 < (p->y - same(q->y))) {
        return 2;
    }
    return 0;
}
'''


def test_each_comparison_and_all_of_them_are_staged():
    out = [text for family, text in stage.variants(SOURCE, 'f') if family == 'compare_operand_stage']
    assert len(out) == 1 or len(out) == 3
    everything = out[-1]
    assert everything.count('__stage_cmp_f32 =') == 2
    assert '__stage_cmp_f32 = p->y - q->y;' in everything and 'if (d1 < __stage_cmp_f32)' in everything
    assert everything.count('f32 __stage_cmp_f32;') == 1


def test_the_staged_expression_drops_an_identity_helper_only():
    source = SOURCE.replace('inline static f32 same(f32 v) { return v; }', 'f32 same(f32 v);')
    out = stage.variants(source, 'f')
    assert not any('= p->y - q->y;' in t for _, t in out)


def test_integer_locals_and_calls_are_left_alone():
    source = 'void f(s32 a, f32 *p) {\n  s32 n;\n  if (n < (a - 1)) { g(); }\n  if (n < (p[0] - h(p[1]))) { g(); }\n}\n'
    assert not stage.variants(source, 'f')
