from decomprepair import callee_layout, floating_initializers

SOURCE = """typedef struct { float x, y, z; } Vec;
float f(Vec *v, Vec *w) {
    float x = v->x;
    float y = v->y;
    float z = w->z;
    w->x = z;
    return x - y;
}
"""


def test_initializer_search_moves_loads_and_keeps_effects():
    proposals = floating_initializers.variants(SOURCE,'f')
    assert any(s.index('float z =') < s.index('float x =') for _,s in proposals)
    assert all(s.endswith('    w->x = z;\n    return x - y;\n}\n') for _,s in proposals)
    assert not floating_initializers.variants(SOURCE.replace('float x, y, z;', 'volatile float x, y, z;'),'f')
    assert not floating_initializers.variants(SOURCE.replace('v->y', 'other()'),'f')[1:]


def test_callee_extent_requires_contiguous_unescaped_writes():
    assert callee_layout.extent('out[0]=1; out[1]=2; out[2]=3;', 'out') == 3
    assert callee_layout.extent('out[0]=1; out[2]=3;', 'out') is None
    assert callee_layout.extent('out[0]=1; out[1]=2; escape(out);', 'out') is None


def test_grouped_float_declarators_keep_type_and_statement_boundaries():
    source = """struct V { float x, y, z; };
void f(const struct V *a, const struct V *b, float *out) {
    float x = a->x, y = b->y, z = a->z;
    *out = x + y - z;
}
"""
    proposals = floating_initializers.variants(source, 'f')
    assert proposals[0][1] == source.replace('x = a->x, y = b->y', 'y = b->y, x = a->x')
    assert all('float ' in proposal and '*out = x + y - z;' in proposal for _, proposal in proposals)
    assert not floating_initializers.variants(source.replace('b->y', 'read(b)'), 'f')


def test_adjacent_grouped_declarations_transfer_tail_loads():
    source = """struct V { float x, y, z, w; };
void f(const struct V *a, const struct V *b, float *out) {
    float aw = a->w, bx = b->x, ax = a->x, bw = b->w;
    float ay = a->y, bz = b->z, by = b->y, az = a->z;
    *out = aw + bx + ax + bw + ay + bz + by + az;
}
"""
    proposals = floating_initializers.variants(source, 'f')
    assert proposals[0][1] == source.replace('ax = a->x, bw = b->w', 'az = a->z, ax = a->x').replace(
        'by = b->y, az = a->z', 'by = b->y, bw = b->w')
    mixed = source.replace('float ay', 'double ay')
    assert all('float aw = a->w, bx = b->x, az = a->z' not in text
               for _, text in floating_initializers.variants(mixed, 'f'))
