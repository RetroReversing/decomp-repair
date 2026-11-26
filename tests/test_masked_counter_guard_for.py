from decomprepair import masked_counter_guard_for as repair

SOURCE = """s32 walk(s32 count)
{
    u32 n;
    u32 i;
    u16 node;

    node = head;
    i = 0;
    if ((count & 0xFFFF) != 0)
    {
        n = count & 0xFFFF;
        do
        {
            node = next[node];
            i++;
        } while ((i & 0xFFFF) < n);
    }
    return node;
}
"""


def children(source):
    return [text for _, text in repair.variants(source, 'walk')]


def test_cached_bound_and_masked_counter_become_a_narrow_for_loop():
    cast, mask = children(SOURCE)
    assert 'u16 i;' in cast
    assert 'for (i = 0; i < ((u16) count); i++) {\nnode = next[node];\n}' in cast
    assert 'for (i = 0; i < (count & 0xFFFF); i++)' in mask
    assert 'do' not in cast and 'u32 n;' not in cast and 'i = 0;\n    if' not in cast


def test_masked_reads_in_the_body_read_the_narrow_counter():
    source = SOURCE.replace('node = next[node];', 'node = next[(i & 0xFFFF)];')
    assert 'node = next[i];' in children(source)[0]


def test_plain_bound_without_a_cache():
    source = (SOURCE.replace('        n = count & 0xFFFF;\n', '').replace('< n)', '< limit)')
              .replace('(count & 0xFFFF) != 0', 'limit != 0'))
    assert [text.count('for (i = 0; i < (limit); i++)') for text in children(source)] == [1]


def test_declines_when_the_counter_or_cache_is_used_elsewhere():
    assert not children(SOURCE.replace('return node;', 'return node + i;'))
    assert not children(SOURCE.replace('return node;', 'return node + n;'))
    assert not children(SOURCE.replace('node = next[node];', 'node = next[i];'))


def test_declines_a_different_bound_or_a_continue():
    assert not children(SOURCE.replace('n = count & 0xFFFF;', 'n = count & 0xFF;'))
    assert not children(SOURCE.replace('node = next[node];', 'if (!node) continue;\n            node = next[node];'))
