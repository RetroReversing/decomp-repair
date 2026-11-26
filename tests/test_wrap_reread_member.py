"""A stepped-and-wrapped member read again before its range test.

Synthetic shape of an object's angle update (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`): on the real 93-instruction
function the plain statements scored 315, the `volatile` member alone 300, and the combined child 0."""
from decomprepair import registry
from decomprepair import wrap_reread_member as m

SOURCE = '''typedef float f32;
typedef struct { f32 angle; char pad[0x20]; } Obj;
extern Obj objs[];

void spin(unsigned short i)
{
    objs[i].angle += 1.0f;
    if (objs[i].angle > 360.0f) {
        objs[i].angle -= 360.0f;
    }
}
'''


def test_volatile_member_with_a_local_then_the_local_alone():
    results = m.variants(SOURCE, 'spin')
    assert [family for family, _ in results] == [m.FAMILY] * 2
    both, local = (text for _, text in results)
    assert 'typedef struct { volatile f32 angle;' in both
    assert 'volatile' not in local
    for text in (both, local):
        assert '{\n    f32 stepped;\n' in text
        assert ('objs[i].angle += 1.0f;\n    stepped = objs[i].angle;\n    if (stepped > 360.0f) {\n'
                '        objs[i].angle = stepped - 360.0f;\n    }\n}') in text


def test_another_member_in_the_wrap_is_left_alone():
    assert m.variants(SOURCE.replace('objs[i].angle -= 360.0f;', 'objs[i].other -= 360.0f;'), 'spin') == []


def test_declared_in_the_registry():
    assert any(repair.module == 'wrap_reread_member' for repair in registry.declared())
