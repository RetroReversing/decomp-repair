"""call_pair_address_share: `&local` passed first to two calls in a row, read through one pointer local that every such
pair shares (a KMC GCC 2.7.2 collision routine: 12757 -> 7266, frame 0x2A0 -> 0x290; one local per pair was 13360).
The source below is made up; it only has that shape."""
from decomprepair import call_pair_address_share as share
from decomprepair import registry

SOURCE = """extern void closest(f32 *, f32 *, f32 *, f32 *);
extern f32 dist2(f32 *, f32 *);
#define edgeB edges[0]
f32 f(f32 *a, f32 *b, f32 *c, f32 *p) {
    f32 edgeA[3];
    f32 edges[4];
    f32 da;
    f32 db;
    closest(&edgeA, a, b, p);
    da = dist2(&edgeA, p);
    closest(&edgeB, b, c, p);
    db = dist2(&edgeB, p);
    closest(p, c, a, &edgeA);
    return da + db + dist2(p, &edgeA);
}
"""


def children(source):
    return [text for _, text in share.variants(source, 'f')]


def test_every_pair_shares_one_pointer_first():
    texts = children(SOURCE)
    assert len(texts) == 3
    text = texts[0]
    assert '    f32 *__repair_point;' in text
    assert '__repair_point = &edgeA; closest(__repair_point, a, b, p);' in text
    assert 'da = dist2(__repair_point, p);' in text
    assert '__repair_point = &edgeB; closest(__repair_point, b, c, p);' in text
    # a pair whose first arguments differ is left alone
    assert 'closest(p, c, a, &edgeA);' in text and 'dist2(p, &edgeA)' in text


def test_each_pair_alone_follows():
    one, two = children(SOURCE)[1:]
    assert 'closest(__repair_point, a, b, p);' in one and 'closest(&edgeB' in one
    assert 'closest(__repair_point, b, c, p);' in two and 'closest(&edgeA, a, b, p);' in two


def test_a_statement_between_the_calls_stops_the_pair():
    assert not children(SOURCE.replace('    da = dist2(&edgeA, p);\n', '    a = b;\n    da = dist2(&edgeA, p);\n')
                        .replace('    db = dist2(&edgeB, p);\n', '    b = c;\n    db = dist2(&edgeB, p);\n'))


def test_it_is_declared_in_the_registry():
    assert 'call_pair_address_share' in {r.module.rsplit('.', 1)[-1] for r in registry.declared()}
