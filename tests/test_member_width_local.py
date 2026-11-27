"""A word local that only holds a narrow struct member, declared that narrow."""
from decomprepair.member_width_local import FAMILY, variants

CODE = '''typedef union {
    struct {
        u8 bank;
        u8 page;
    } split;
    u16 whole;
} Unit;
extern int load(int bank);
int walk(Unit unit, Unit *next, int first)
{
    s32 count;
    s32 last;

    count = 0;
    last = 0xFF;
    while (1) {
        if (unit.whole >= first) {
            if (unit.split.bank != last) {
                last = unit.split.bank;
                load(last);
            }
            count++;
            unit = next[unit.split.page];
        } else {
            break;
        }
    }
    return count;
}
'''


def test_the_local_takes_the_members_type():
    children = variants(CODE, 'walk')
    assert children == [(FAMILY, CODE.replace('s32 last;', 'u8 last;'))]


def test_member_types_come_from_the_header_too():
    struct, rest = CODE.split('extern int load', 1)
    source = 'extern int load' + rest
    assert variants(source, 'walk') == []
    assert variants(source, 'walk', struct) == [(FAMILY, source.replace('s32 last;', 'u8 last;'))]


def test_a_value_the_narrow_type_would_change_is_left_alone():
    assert variants(CODE.replace('last = 0xFF;', 'last = -1;'), 'walk') == []
    assert variants(CODE.replace('last = 0xFF;', 'last = first;'), 'walk') == []
    assert variants(CODE.replace('s32 last;', 'u32 last;'), 'walk') == []
    assert variants(CODE.replace('load(last);', 'load(last);\n                last++;'), 'walk') == []
    assert variants(CODE.replace('load(last);', 'load((int) &last);'), 'walk') == []
    assert variants(CODE.replace('count++;', 'count++;\n            last += 1;'), 'walk') == []


def test_a_member_name_with_two_types_is_left_alone():
    assert variants(CODE.replace('extern int load', 'struct Other { int bank; };\nextern int load'), 'walk') == []
