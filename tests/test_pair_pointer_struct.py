"""Two neighbouring scalar globals reached through a pointer, written as the two members of a record."""
import re

from decomprepair import registry
from decomprepair.pair_pointer_struct import FAMILY, variants

CODE = '''typedef int s32;
typedef float f32;
extern s32 gSum;
extern s32 gLast;
extern s32 gIndex;

void f(unsigned char *buf, s32 y)
{
    s32 *pa;
    s32 *pb;
    s32 r;
    pa = &gSum;
    pb = pa + 1;
    *pa = buf[y];
    *pa += buf[gIndex + y];
    r = (s32) ((f32) *pa * 0.5f);
    *pb = r;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_pair_becomes_a_record_pointer_and_its_second_member():
    [(family, child)] = variants(CODE, 'f')
    text = squash(child)
    assert family == FAMILY
    assert 'typedef struct { s32 a; s32 b; } Pair_gSum; void f(' in text
    assert 'Pair_gSum *pa; s32 *pb;' in text
    assert 'pa = (Pair_gSum *) &gSum; pb = &pa->b;' in text
    assert 'pa->a = buf[y]; pa->a += buf[gIndex + y];' in text
    assert '(f32) pa->a * 0.5f' in text and '*pb = r;' in text


def test_a_product_with_the_pointer_is_not_a_dereference():
    code = CODE.replace('(f32) *pa * 0.5f', '(f32) r * *pa')
    [(_, child)] = variants(code, 'f')
    assert 'r * pa->a' in squash(child)
    assert variants(CODE.replace('*pa = buf[y];', 'r = y * *pa;').replace('*pa += buf[gIndex + y];', 'r = r * y * *pa;').replace('(f32) *pa * 0.5f', '(f32) y'), 'f') != []


def test_a_pointer_that_moves_or_a_single_use_is_left_alone():
    assert variants(CODE.replace('*pa += buf[gIndex + y];', 'pa++;'), 'f') == []
    assert variants(CODE.replace('*pa += buf[gIndex + y];', '').replace('(f32) *pa * 0.5f', '(f32) y'), 'f') == []
    assert variants(CODE.replace('pb = pa + 1;', 'pb = pa + 2;'), 'f') == []


def test_mismatched_pointer_types_are_left_alone():
    assert variants(CODE.replace('s32 *pb;', 'unsigned char *pb;'), 'f') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []
