"""A run of byte-offset stores written out of order, put in order of their offsets."""
from decomprepair import offset_store_order as p

# A 4x4 rotation-matrix builder in m2c's spelling (KMC GCC 2.7.2): the zero words first, the products in the order
# m2c found them, a float's bits stored as a word, a dead copy of one product. 160 in this order, 35 in order of offsets.
SOURCE = '''f32 __cosf(f32);
f32 sinApprox(f32);

void build(void *arg0, f32 arg1, f32 arg2, f32 arg3, f32 arg4) {
    register f32 zero = 0.0f;
    f32 sx;
    f32 cx;
    f32 sy;
    f32 cy;
    f32 t;
    f32 u;

    sx = sinApprox(arg1);
    cx = __cosf(arg1);
    sy = sinApprox(arg2);
    cy = __cosf(arg2);
    t = cx * sy;
    (*(f32 *)((char *)(arg0) + 0x2C)) = zero;
    (*(f32 *)((char *)(arg0) + 0xC)) = zero;
    (*(f32 *)((char *)(arg0) + 8)) = (f32) -sy;
    (*(f32 *)((char *)(arg0) + 0x30)) = arg4;
    (*(f32 *)((char *)(arg0) + 0)) = (f32) (cy * sx);
    (*(f32 *)((char *)(arg0) + 0x10)) = (f32) (cx * cy);
    { union { f32 f; int i; } v; v.f = cy * sy; *(int *)((char *)arg0 + 4) = v.i; }
    u = t * cy;
    (*(f32 *)((char *)(arg0) + 0x20)) = (f32) (u + sx);
    (*(f32 *)((char *)(arg0) + 0x14)) = (f32) (sx * sy);
}
'''


def stores(text):
    return [line.strip() for line in text.splitlines() if '(arg0)' in line or 'arg0 + 4' in line]


def offsets(text):
    out = []
    for line in stores(text):
        if 'arg0 + 4' in line:
            out.append(4)
        else:
            out.append(int(line.split('+ ')[1].split(')')[0], 0))
    return out


def children(source=SOURCE):
    return dict(p.variants(source, 'build'))


def test_the_stores_come_out_in_order_of_their_offsets():
    kids = children()
    for family in (p.FAMILY, p.FAMILY_HOISTED):
        assert offsets(kids[family]) == sorted(offsets(SOURCE))


def test_descending_is_the_other_end():
    assert offsets(children()[p.FAMILY_DESCENDING]) == sorted(offsets(SOURCE), reverse=True)


def test_a_store_keeps_the_local_it_reads_before_it():
    for text in children().values():
        assert text.index('u = t * cy;') < text.index('(u + sx)')
        assert text.index('t = cx * sy;') < text.index('u = t * cy;')


def test_the_local_goes_just_before_its_store_or_to_the_top():
    kids = children()
    lazy, hoisted = kids[p.FAMILY], kids[p.FAMILY_HOISTED]
    lines = [line.strip() for line in lazy.splitlines()]
    assert lines.index('u = t * cy;') == lines.index('(*(f32 *)((char *)(arg0) + 0x20)) = (f32) (u + sx);') - 1
    top = [line.strip() for line in hoisted.splitlines()]
    assert top.index('u = t * cy;') < top.index('(*(f32 *)((char *)(arg0) + 0)) = (f32) (cy * sx);')


def test_the_union_store_moves_whole():
    for text in children().values():
        assert '{ union { f32 f; int i; } v; v.f = cy * sy; *(int *)((char *)arg0 + 4) = v.i; }' in text


def test_nothing_changes_when_the_stores_are_in_order():
    text = children()[p.FAMILY_HOISTED]
    for family, body in p.variants(text, 'build'):
        if family != p.FAMILY_DESCENDING:
            assert offsets(body) == offsets(text)


def test_a_call_ends_the_run():
    text = SOURCE.replace('    u = t * cy;\n', '    u = t * cy;\n    sinApprox(u);\n')
    for body in children(text).values():
        # the three stores after the call are too few to reorder, and the ones before it keep to their side
        assert body.index('sinApprox(u);') > body.index('(cx * cy)')
        assert body.index('sinApprox(u);') < body.index('(u + sx)')


def test_a_second_pointer_ends_the_run():
    text = SOURCE.replace('(*(f32 *)((char *)(arg0) + 0x10))', '(*(f32 *)((char *)(other) + 0x10))')
    for body in children(text).values():
        assert body.index('(cx * cy)') < body.index('(u + sx)')


def test_overlapping_stores_are_left_alone():
    text = SOURCE.replace('(*(f32 *)((char *)(arg0) + 0x10))', '(*(f32 *)((char *)(arg0) + 0x12))')
    assert children(text) == {}


def test_a_store_that_reads_memory_is_a_barrier():
    text = SOURCE.replace('(cy * sx)', '(*(f32 *)arg1 * sx)')
    for body in children(text).values():
        assert body.index('0x2C') < body.index('(cx * cy)')


def test_the_constant_index_form_is_sorted_too():
    source = '''void build(f32 *m, f32 a, f32 b) {
    f32 t;

    t = a * b;
    m[3] = t;
    m[1] = a;
    m[2] = b;
    m[0] = t + a;
}
'''
    kids = dict(p.variants(source, 'build'))
    assert kids
    body = next(iter(kids.values()))
    order = [line.split('[')[1][0] for line in body.splitlines() if line.strip().startswith('m[')]
    assert order == ['0', '1', '2', '3']


def test_the_module_declares_itself():
    from decomprepair import registry
    assert 'offset_store_order' in {r.module for r in registry.declared()}
