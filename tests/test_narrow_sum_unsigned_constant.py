"""A sum stored into a halfword, whose 16-bit constant is written unsigned."""
import re

from decomprepair.narrow_sum_unsigned_constant import FAMILY, variants

CODE = '''typedef short s16;
typedef unsigned short u16;
extern u16 gBase;
extern u16 gTable[];
void run(void *q, s16 x)
{
    (*(u16 *)((char *)q + 0x20)) = gBase + (x + 0xFFC7);
    *((u16 *) (((char *) q) + 0x22)) = x + 0x12;
    (*(s16 *)((char *)q + 0x24)) = gBase + (x + 0xFFDB);
    gBase = x + 0xFFC7;
    gTable[1] = gBase + (x + 0xFFDB);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_constants_of_halfword_stores_get_the_unsigned_suffix():
    children = variants(CODE, 'run')
    assert [family for family, _ in children] == [FAMILY]
    text = squash(children[0][1])
    assert '= gBase + (x + 0xFFC7U);' in text and '= gBase + (x + 0xFFDBU);' in text
    assert 'x + 0x12;' in text and 'gBase = x + 0xFFC7U;' in text and 'gTable[1] = gBase + (x + 0xFFDBU);' in text


def test_other_constants_and_already_suffixed_ones_are_left_alone():
    assert variants(CODE.replace('0xFFC7', '0x7FC7').replace('0xFFDB', '0x7FDB'), 'run') == []
    assert variants(CODE.replace('0xFFC7', '0xFFC7U').replace('0xFFDB', '0xFFDBU'), 'run') == []
    assert variants(CODE, 'missing') == []


def test_a_store_inside_a_one_shot_scope_is_read_too():
    code = CODE.replace('    gTable[1] = gBase + (x + 0xFFDB);', '    do { gTable[1] = gBase + (x + 0xFFDB); } while (0);')
    assert 'do { gTable[1] = gBase + (x + 0xFFDBU); } while (0);' in squash(variants(code, 'run')[0][1])
