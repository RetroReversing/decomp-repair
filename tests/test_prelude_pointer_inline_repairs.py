from decomprepair.prelude_pointer_inline_repairs import FAMILY, variants

SOURCE = '''void f(void *arg0, s32 mode)
{
    void *entry;
    void *alias;
    s32 a;
    s32 b;
    entry = *(void **)((char *)arg0 + 0x68);
    alias = (void *)entry;
    a = *(s8 *)((char *)alias + 0xE);
    b = *(s8 *)((char *)alias + 0x10);
    switch (mode)
    {
        case 0:
            alias = *(void **)((char *)arg0 + 0x68);
            use(alias, a, b);
            break;
    }
}
'''


def test_entry_pointer_is_written_at_each_use():
    found = [text for family, text in variants(SOURCE, 'f') if family == FAMILY]
    assert found
    everything = found[-1]
    assert 'entry =' not in everything and 'alias = (void *)entry' not in everything
    assert everything.count('*(void **)((char *)arg0 + 0x68)') == 3
    assert 'use(alias, a, b)' in everything


def test_value_read_after_the_prelude_is_kept():
    read_later = SOURCE.replace('alias = *(void **)((char *)arg0 + 0x68);\n            use(', 'use(', 1)
    assert not [1 for _, text in variants(read_later, 'f') if 'alias = (void *)entry' not in text]
