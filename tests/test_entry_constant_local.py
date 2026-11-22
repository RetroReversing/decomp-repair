"""entry_constant_local: a byte constant the loop compares against, as a local set among the entry assignments.

Synthetic shape of the 219-instruction sequencer function: counters set to 0 and a flag to 1 before a loop whose body
tests several bytes against 0xFF; the target's prologue has the `li 0xFF` between two of the counter moves."""
from decomprepair import entry_constant_local as s

SOURCE = '''s32 walk(u8 *table, s32 count)
{
    s32 flag;
    s32 index;
    s32 offset;
    s32 total;
    u8 value;
    flag = 1;
    index = 0;
    offset = 0;
    do {
        value = table[offset];
        if (value != 0xFF) {
            total += value;
        }
        if (table[offset + 1] != 0xFF) {
            flag = 0;
        }
        offset += 16;
        index += 1;
    } while (index < count);
    return flag + total;
}
'''


def test_every_place_in_the_entry_run_gets_the_constant_local():
    found = s.variants(SOURCE, 'walk')
    assert len(found) == 4
    assert all(family == s.FAMILY for family, _ in found)
    sources = [text for _, text in found]
    for text in sources:
        assert text.count('const_0xff') == 4  # the declaration, the assignment and the two comparisons' uses
        assert '!= const_0xff' in text and '!= 0xFF' not in text
    order = []
    for text in sources:
        lines = [line.strip() for line in text.splitlines()]
        entry = [line for line in lines if line.endswith(';') and ' = ' in line and line.split()[0] in ('flag', 'index', 'offset', 'const_0xff')][:4]
        order.append([line.split()[0] for line in entry])
    assert order == [['const_0xff', 'flag', 'index', 'offset'], ['flag', 'const_0xff', 'index', 'offset'],
                     ['flag', 'index', 'const_0xff', 'offset'], ['flag', 'index', 'offset', 'const_0xff']]


def test_one_comparison_or_a_small_constant_is_left_alone():
    one = SOURCE.replace('table[offset + 1] != 0xFF', 'table[offset + 1] != 3')
    assert s.variants(one, 'walk') == []
    assert s.variants(SOURCE.replace('0xFF', '7'), 'walk') == []


def test_no_loop_or_no_entry_run_gives_nothing():
    assert s.variants(SOURCE.replace('do {', 'if (1) {').replace('} while (index < count);', '}'), 'walk') == []
    bare = SOURCE.replace('    flag = 1;\n    index = 0;\n    offset = 0;\n', '')
    assert s.variants(bare, 'walk') == []
