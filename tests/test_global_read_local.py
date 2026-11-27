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


MEMBERS = '''typedef unsigned short u16;
typedef int s32;
extern u16 gSerial;
typedef struct { char pad[8]; u16 tag; char pad2[2]; s32 id; char state; } Item;

void f(void *item)
{
    (((Item *) item)->state) = 3;
    (((Item *) item)->tag) = (u16) gSerial;
    (((Item *) item)->id) = (s32) (gSerial & 0xFFFF);
}
'''


def test_a_member_store_is_a_store_through_a_pointer():
    for code in (MEMBERS, MEMBERS.replace('((Item *) item)->', 'rec->')):
        [(_, child)] = variants(code, 'f')
        text = squash(child)
        assert 'u16 held_gSerial;' in text
        assert text.index('held_gSerial = gSerial;') < text.index('->state) = 3;')
        assert '(u16) held_gSerial;' in text and '(held_gSerial & 0xFFFF)' in text


def test_a_member_read_into_a_local_is_not_a_store():
    code = MEMBERS.replace('(((Item *) item)->state) = 3;', 's32 s;\n    s = ((Item *) item)->state;')
    code = code.replace('(((Item *) item)->tag) = (u16) gSerial;', 's += gSerial;').replace(
        '(((Item *) item)->id) = (s32) (gSerial & 0xFFFF);', 's += gSerial & 3;')
    assert variants(code, 'f') == []


def test_expanded_field_stores_count_as_pointer_stores():
    code = """extern u16 gSerial;
void f(void *p)
{
    (*(s8 *)((char *)(p) + 0x78)) = 3;
    (*(u16 *)((char *)(p) + 0x6A)) = (u16) gSerial;
    (*(s32 *)((char *)(p) + 0x34)) = (s32) (gSerial & 0xFFFF);
}
"""
    [(_, child)] = variants(code, 'f')
    text = squash(child)
    assert text.index('held_gSerial = gSerial;') < text.index('0x78)) = 3;')
    assert '(u16) held_gSerial' in text and '(held_gSerial & 0xFFFF)' in text
