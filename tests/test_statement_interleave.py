"""Moving one assignment across independent neighbours: proposals only, nothing is compiled here."""
from decomprepair.statement_interleave import variants

BODY = '''void f(Obj *o, Bone *b, Mtx *m) {
    f32 tx;
    f32 ty;
    o->p.x = 1;
    sp.x = m->t.x + o->pos.x;
    tx = b->b.x;
    sp.y = m->t.y + o->pos.y;
    ty = b->b.y;
    use(&sp, tx, ty);
}
'''


def _all(text, name='f'):
    return [src for fam, src in variants(text, name) if fam == 'statement_interleave']


def test_a_statement_moves_across_independent_neighbours():
    srcs = _all(BODY)
    assert any(s.index('tx = b->b.x;') < s.index('sp.x = ') for s in srcs)
    assert any(s.index('sp.y = ') < s.index('tx = b->b.x;') for s in srcs)


def test_every_proposal_keeps_the_same_statements():
    for src in _all(BODY):
        assert sorted(src.splitlines()) == sorted(BODY.splitlines())


def test_dependent_statements_never_cross():
    text = BODY.replace('ty = b->b.y;', 'ty = tx + 1;')
    for src in _all(text):
        assert src.index('tx = b->b.x;') < src.index('ty = tx + 1;')


def test_calls_pointer_stores_and_other_arch_are_left_alone():
    assert not _all('void f(A *a) {\n    a->x = 1;\n    a->y = 2;\n}\n')
    assert not _all('void f(void) {\n    x = g();\n    y = h();\n}\n')
    assert variants(BODY, 'f', 'x86') == []


def test_proposals_are_capped_and_distinct():
    many = 'void f(void) {\n' + ''.join(f'    v{i} = a{i} + 1;\n' for i in range(12)) + '}\n'
    srcs = _all(many)
    assert len(srcs) == len(set(srcs)) <= 48
