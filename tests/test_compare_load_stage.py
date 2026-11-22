"""The value a result is compared with, read into a local before the store of that result.

Synthetic shape of the 851-instruction ray test's room loop: a distance returned by a helper is stored into a local
record, then compared with a radius read through a pointer. The target loads the radius before the store."""
from decomprepair import compare_load_stage as c

SOURCE = '''typedef struct { f32 d8; f32 d16; } Work;
s32 hit(void *a, void *obj)
{
    Work work;
    f32 dist;
    f32 best;
    s32 found;
    found = 0;
    dist = measure(a, obj);
    work.d8 = dist;
    if (dist < M2C_FIELD(obj, f32 *, 0x4C)) {
        found = 1;
        best = work.d8;
    }
    return found + (s32) best;
}
'''


def _texts(source=SOURCE):
    found = c.variants(source, 'hit')
    assert all(family == c.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_compared_load_is_read_into_a_local_before_the_store():
    [text] = _texts()
    assert '    f32 __compare_load0;\n' in text.split('found = 0;')[0]
    assert '    __compare_load0 = M2C_FIELD(obj, f32 *, 0x4C);\n    work.d8 = dist;\n    if (dist < __compare_load0) {' in text


def test_the_local_is_declared_after_the_existing_ones():
    [text] = _texts()
    assert text.index('s32 found;') < text.index('f32 __compare_load0;') < text.index('found = 0;')


def test_a_member_read_is_staged_too():
    text = SOURCE.replace('M2C_FIELD(obj, f32 *, 0x4C)', 'limit->radius').replace('void *obj', 'Lim *limit')
    assert any('__compare_load0 = limit->radius;' in t for t in _texts(text))


def test_a_call_in_the_compared_expression_is_left_alone():
    text = SOURCE.replace('M2C_FIELD(obj, f32 *, 0x4C)', 'radius(obj)')
    assert _texts(text) == []


def test_a_store_that_is_not_directly_before_the_test_is_left_alone():
    text = SOURCE.replace('    work.d8 = dist;\n', '    work.d8 = dist;\n    found = 2;\n')
    assert _texts(text) == []


def test_two_sites_are_offered_alone_and_together():
    text = SOURCE.replace('    return found', '    work.d16 = dist;\n    if (dist < M2C_FIELD(obj, f32 *, 0x50)) {\n        found = 3;\n    }\n    return found')
    texts = _texts(text)
    assert len(texts) == 3
    assert any('__compare_load0 = M2C_FIELD(obj, f32 *, 0x4C);' in t and '__compare_load1 = M2C_FIELD(obj, f32 *, 0x50);' in t for t in texts)
