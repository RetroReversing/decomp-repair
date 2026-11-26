"""constant_channel_locals: a literal stored into several fields of each record of a run, as one local per field.

Synthetic shape of the 262-instruction display-list builder: calls, then four vertices whose four colour bytes are
0xFF, stored in an order tuned to another allocation; the exact source set one local per colour byte at the entry and
wrote the vertices field by field."""
from decomprepair import constant_channel_locals as s

STORES = '''    v[0].ob[0] = -size;
    v[0].cn[0] = 0xFF;
    v[0].ob[1] = -size;
    v[0].cn[1] = 0xFF;
    v[0].cn[2] = 0xFF;
    v[0].cn[3] = 0xFF;
    v[0].tc[0] = s[0];
    v[1].ob[0] = size;
    v[1].cn[0] = 0xFF;
    v[1].cn[1] = 0xFF;
    v[1].cn[2] = 0xFF;
    v[1].cn[3] = 0xFF;
    v[0].tc[1] = t[0];
    v[1].tc[0] = s[1];
    v[1].ob[1] = -size;
    v[1].tc[1] = t[1];
'''

SOURCE = '''void build(Vtx *unused, s32 zoom)
{
    s32 s[2];
    s32 t[2];
    s32 size;

    size = 600;
    setup(zoom);
    fill(s, t);
''' + STORES.replace('    v[', '    D_8013FB30[') + '''    finish();
}
'''


def test_one_local_per_field_at_the_entry_and_the_run_in_field_order():
    found = s.variants(SOURCE, 'build')
    assert found and all(family == s.FAMILY for family, _ in found)
    texts = [text for _, text in found]
    assert len(texts) == 4  # before the first statement and after `size = 600;`, each plain and in field order
    for text in texts:
        assert '0xFF' not in text.split('fill(s, t);')[1]
        for index in range(4):
            assert f'    s32 cn{index}_k;\n' in text and f'    cn{index}_k = 0xFF;\n' in text
            assert f'D_8013FB30[0].cn[{index}] = cn{index}_k;' in text
        assert text.index('cn0_k = 0xFF;') < text.index('setup(zoom);')
    first, after = texts[0], texts[2]
    assert first.index('cn3_k = 0xFF;') < first.index('size = 600;')
    assert after.index('size = 600;') < after.index('cn0_k = 0xFF;')
    ordered = texts[1].split('fill(s, t);\n')[1].split('    finish();')[0].split('\n')[:-1]
    assert [line.split(' = ')[0].strip() for line in ordered] == [
        f'D_8013FB30[{v}].{f}' for v in range(2) for f in ('ob[0]', 'ob[1]', 'cn[0]', 'cn[1]', 'cn[2]', 'cn[3]',
                                                           'tc[0]', 'tc[1]')]
    assert 'D_8013FB30[1].ob[1] = -size;' in texts[1] and 'D_8013FB30[0].tc[1] = t[0];' in texts[1]


def test_no_call_before_the_run_or_too_few_fields_gives_nothing():
    leaf = SOURCE.replace('    setup(zoom);\n    fill(s, t);\n', '')
    assert s.variants(leaf, 'build') == []
    one_field = SOURCE.replace('.cn[1] = 0xFF', '.cn[1] = 0').replace('.cn[2] = 0xFF', '.cn[2] = 0').replace(
        '.cn[3] = 0xFF', '.cn[3] = 0')
    assert s.variants(one_field, 'build') == []


def test_a_value_that_reads_the_records_or_calls_is_left_alone():
    reads = SOURCE.replace('D_8013FB30[0].tc[1] = t[0];', 'D_8013FB30[0].tc[1] = D_8013FB30[0].tc[0];')
    assert s.variants(reads, 'build') == []
    calls = SOURCE.replace('D_8013FB30[0].tc[1] = t[0];', 'D_8013FB30[0].tc[1] = next();')
    assert s.variants(calls, 'build') == []
