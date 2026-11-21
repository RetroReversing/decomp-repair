"""Float temporaries written out in the stores that use them, the stores in index order."""
from decomprepair import store_expression_forms as p

SOURCE = '''void f(const s16 *angles, f32 *matrix)
{
    f32 cx, sx, cy, sy, cz, sz;
    f32 czsy, szsy, szcx, szsx, czcx, czsx;
    f32 m01, m02, m11, m12;

    cx = __cosf(angles[0]);
    sx = sinApprox(angles[0]);
    cy = __cosf(angles[1]);
    sy = sinApprox(angles[1]);
    cz = __cosf(angles[2]);
    sz = sinApprox(angles[2]);
    czsy = cz * sy;
    szsy = sz * sy;
    szcx = sz * cx;
    szsx = sz * sx;
    czcx = cz * cx;
    czsx = cz * sx;
    m01 = czsy * sx;
    m02 = czsy * cx;
    m11 = szsy * sx;
    m01 -= szcx;
    sy = -sy;
    m02 += szsx;
    m12 = szsy * cx;
    matrix[6] = sy;
    m11 += czcx;
    matrix[0] = cz * cy;
    matrix[3] = sz * cy;
    matrix[7] = cy * sx;
    matrix[8] = cy * cx;
    m12 -= czsx;
    matrix[1] = m01;
    matrix[2] = m02;
    matrix[4] = m11;
    matrix[5] = m12;
}
'''


def test_every_temporary_is_written_out_and_the_stores_go_in_index_order():
    # A rotation-matrix builder (GCC 2.7.2): 15 with the temporaries, exact with both changes together.
    outs = [text for _, text in p.variants(SOURCE, 'f')]
    assert len(outs) == 2
    kept, ordered = outs
    assert 'matrix[1] = (cz * sy) * sx - (sz * cx);' in kept
    assert 'matrix[4] = (sz * sy) * sx + (cz * cx);' in kept
    assert 'matrix[5] = (sz * sy) * cx - (cz * sx);' in kept
    # sy is negated after products read it: the products keep the old value, the store gets the negation
    assert 'matrix[6] = -sy;' in kept and 'sy = -sy' not in kept
    assert kept.index('matrix[6]') < kept.index('matrix[0]')
    lines = [line.strip() for line in ordered.splitlines() if line.strip().startswith('matrix[')]
    assert [line[7] for line in lines] == list('012345678')
    for out in outs:
        assert 'czsy =' not in out and 'm01' not in out.split('{', 1)[1].split('sinApprox(angles[2]);')[1]
        assert out.count('__cosf') == 3  # the calls stay where they were


def test_left_alone_when_unsafe():
    # a temporary read after the run
    assert p.variants(SOURCE.replace('}\n', '    g(m12);\n}\n'), 'f') == []
    # a loop could read the temporaries again
    assert p.variants(SOURCE.replace('    czsy = cz * sy;', '    if (cx) {\n    czsy = cz * sy;'), 'f') == []
    # stores that read memory cannot be reordered
    assert p.variants(SOURCE.replace('matrix[2] = m02;', 'matrix[2] = matrix[0] + m02;'), 'f') == []
    # a temporary that is not a float is not written out (its assignment narrows): its statement stays
    outs = p.variants(SOURCE.replace('f32 czsy, szsy,', 's32 czsy; f32 szsy,'), 'f')
    assert outs and all('czsy = cz * sy;' in text for _, text in outs)
