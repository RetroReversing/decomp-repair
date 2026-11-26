import re

from decomprepair import consumed_value_reuse
from decomprepair.consumed_value_reuse import FAMILY, variants

SOURCE = """float root(float);
typedef struct { float x, y; } V;

void clamp(V *a, V *b) {
    f32 len, s;

    len = root(a->x * a->x + a->y * a->y);
    if (len > 9.0f) {
        s = 9.0f / len;
        a->x = s * a->x;
        a->y = s * a->y;
    }
    len = root(b->x * b->x + b->y * b->y);
    if (len > 9.0f) {
        s = 9.0f / len;
        b->x = s * b->x;
        b->y = s * b->y;
    }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_every_site_in_one_child_first():
    children = variants(SOURCE, 'clamp')
    assert [f for f, _ in children] == [FAMILY] * 3
    first = _flat(children[0][1])
    assert first.count('len = 9.0f / len;') == 2
    assert 'a->y = len * a->y;' in first and 'b->y = len * b->y;' in first
    assert 's *' not in first


def test_one_site_alone():
    one = _flat(variants(SOURCE, 'clamp')[1][1])
    assert 'a->x = len * a->x;' in one and 'b->x = s * b->x;' in one


def test_a_source_read_again_is_left_alone():
    source = SOURCE.replace('a->y = s * a->y;', 'a->y = s * len;').replace('b->y = s * b->y;', 'b->y = s * len;')
    assert variants(source, 'clamp') == []


def test_a_value_read_after_the_block_is_left_alone():
    source = SOURCE.replace('    }\n}\n', '    }\n    b->x = s;\n}\n')
    assert all('b->x = len' not in child for _, child in variants(source, 'clamp'))


def test_declared():
    assert consumed_value_reuse.REPAIR['families'] == (FAMILY,)
