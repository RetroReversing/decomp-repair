"""A loop variable that is passed as a call's argument gets its own local (a 219-instruction N64 function)."""
from decomprepair import argument_loop_split as a

SOURCE = '''void walk(u16 *key, u16 *list, s32 table)
{
    s32 lookup;
    while ((lookup = *key) != 0xffff) {
        if (*(u16 *)(list + 4) == (u16)lookup) {
            hit(key);
        }
        key++;
    }
    while ((lookup = *(list++)) != 0xffff) {
        note(lookup, table);
    }
}
'''


def _texts(source=SOURCE):
    found = a.variants(source, 'walk')
    assert all(family == a.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_argument_loop_gets_its_own_local():
    out, = _texts()
    assert 'while ((lookup_arg = *(list++)) != 0xffff) {\n        note(lookup_arg, table);' in out
    assert out.index('s32 lookup_arg;') > out.index('s32 lookup;')
    assert 'while ((lookup = *key) != 0xffff)' in out


def test_a_variable_used_only_in_its_argument_loop_is_left_alone():
    assert _texts(SOURCE.replace('while ((lookup = *key) != 0xffff)', 'while (*key != 0xffff)').replace('(u16)lookup', '1')) == []


def test_a_loop_without_the_argument_is_left_alone():
    assert _texts(SOURCE.replace('note(lookup, table)', 'note(table)')) == []
