"""A float stored into a narrow field through an int cast, converted directly; the masked update reusing a local."""
import re

from decomprepair.narrow_conversion_direct import FAMILY, REUSE, variants

CODE = '''typedef int s32;
typedef short s16;
typedef float f32;
typedef struct { unsigned int flags; s16 a; s16 b; f32 f; } Rec;
s32 init(Rec *rec, Rec *obj, s32 n)
{
    s32 temp;
    s32 i;
    s32 j;
    for (i = 0; i < n; i++) {
        rec->a += i;
    }
    rec->a = (s16) ((s32) obj->f);
    rec->b = 0;
    temp = rec->flags & 3;
    rec->flags = temp | 0x8010;
    for (i = 0; i < n; i++) {
        rec->b += i;
    }
    return n;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_conversion_is_written_directly_alone_and_with_the_update_in_the_loop_counter():
    children = variants(CODE, 'init')
    assert [family for family, _ in children] == [FAMILY, REUSE, REUSE]
    alone = squash(children[0][1])
    assert 'rec->a = (s16) (obj->f);' in alone and 'temp = rec->flags & 3;' in alone
    first = squash(children[1][1])
    assert 'rec->a = (s16) (obj->f);' in first
    assert 'i = rec->flags & 3; rec->flags = i | 0x8010; for (i = 0;' in first
    assert 'j = rec->flags & 3;' in squash(children[2][1])


def test_a_local_read_after_the_update_or_with_its_address_taken_is_not_reused():
    read_after = CODE.replace('    return n;', '    return n + j;')
    assert [family for family, _ in variants(read_after, 'init')] == [FAMILY, REUSE]
    taken = CODE.replace('    return n;', '    j = 0; use(&j);\n    return n;')
    assert all('j = rec->flags' not in squash(text) for _, text in variants(taken, 'init'))


def test_a_wide_or_plain_conversion_is_left_alone():
    assert variants(CODE.replace('(s16) ((s32) obj->f)', '(s32) ((s32) obj->f)'), 'init') == []
    assert variants(CODE.replace('(s16) ((s32) obj->f)', '(s16) obj->f'), 'init') == []
