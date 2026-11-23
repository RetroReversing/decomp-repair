"""A stored local's next call argument read back from the store, with the local's step moved above the call."""
import re

from decomprepair.stored_value_call_reread import FAMILY, variants

CODE = '''typedef int s32;
typedef struct { s32 rec; s32 a; } Obj;
extern void *alloc(s32);
extern void clear(void *, s32, s32);
s32 init(Obj *obj, s32 size)
{
    s32 p;
    s32 q;
    p = (s32) alloc(size);
    if (p != 0) {
        obj->rec = p;
        clear((void *) p, 0, 0xB8);
        q = obj->rec;
        p += 0xB8;
        ((Obj *) q)->a = p;
    }
    return p;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_call_reads_the_field_and_the_step_comes_first():
    children = variants(CODE, 'init')
    assert [family for family, _ in children] == [FAMILY]
    text = squash(children[0][1])
    assert 'obj->rec = p; p += 0xB8; clear((void *) obj->rec, 0, 0xB8); q = obj->rec; ((Obj *) q)->a = p;' in text


def test_a_read_before_the_step_a_global_or_an_address_taken_local_is_left_alone():
    assert variants(CODE.replace('        q = obj->rec;\n', '        q = p;\n'), 'init') == []
    assert variants(CODE.replace('    s32 p;\n', '').replace('typedef int s32;\n', 'typedef int s32;\ns32 p;\n'),
                    'init') == []
    assert variants(CODE.replace('    return p;', '    clear(&p, 0, 4);\n    return p;'), 'init') == []
