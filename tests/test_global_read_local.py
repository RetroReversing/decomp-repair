"""A global read again after stores through a pointer, read once into a local before the first store."""
import re

from decomprepair import registry
from decomprepair.global_read_local import FAMILY, variants

CODE = '''typedef unsigned char u8;
typedef int s32;
extern s32 gIndex;
extern s32 gWidth;
extern s32 gSum;

void f(u8 *buf, s32 y, s32 r)
{
    s32 *pa;
    pa = &gSum;
    *pa = buf[y + r];
    *pa += buf[y + 1];
    *pa += buf[gIndex + r];
    *pa += buf[gIndex + 2];
    gWidth = *pa;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_global_is_read_once_above_the_first_store():
    [(family, child)] = variants(CODE, 'f')
    assert family == FAMILY
    text = squash(child)
    assert 's32 held_gIndex;' in text
    assert text.index('held_gIndex = gIndex;') < text.index('*pa = buf[y + r];')
    assert '*pa += buf[held_gIndex + r];' in text and '*pa += buf[held_gIndex + 2];' in text
    assert len(re.findall(r'\bgIndex\b', text)) == 2  # the extern and the one read


def test_a_single_read_after_the_stores_is_left_alone():
    assert variants(CODE.replace('    *pa += buf[gIndex + 2];\n', ''), 'f') == []


def test_a_call_or_a_write_to_the_global_in_the_run_is_left_alone():
    assert variants(CODE.replace('    *pa += buf[gIndex + 2];', '    gIndex = 3;'), 'f') == []
    assert variants(CODE.replace('    *pa += buf[gIndex + 2];', '    h(buf);'), 'f') == []


def test_a_store_to_a_plain_local_is_not_a_pointer_store():
    assert variants(CODE.replace('*pa', 'r'), 'f') == []


def test_a_global_read_before_the_first_store_and_after_it_is_held_from_the_first_read():
    code = CODE.replace('    *pa = buf[y + r];', '    *pa = buf[gIndex];')
    [(_, child)] = variants(code, 'f')
    text = squash(child)
    assert text.index('held_gIndex = gIndex;') < text.index('*pa = buf[held_gIndex];')


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []
