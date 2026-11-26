"""last_read_base_reassign: the last of several same-base reads reassigns the base, the earlier read held in a local.

Synthetic shape of a KMC GCC 2.7.2 sort comparator (saved best 10 rows -> 0 by hand): the target sums the last lookup
into the dying base register."""
from decomprepair import last_read_base_reassign as s

SOURCE = '''s32 cmp(void *arg0, void *arg1) {
    u8 *temp;
    u16 *temp2;

    temp = gTable;
    temp2 = (u16 *)((s8 *)(temp + ((*(u8 *)((s8 *)arg1 + 0xA)) * 0x510)) + 0x418);
    return (*temp2) - (*(u16 *)((s8 *)(temp + ((*(u8 *)((s8 *)arg0 + 0xA)) * 0x510)) + 0x418));
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'cmp') if family == s.FAMILY]


def test_the_hand_matched_shape():
    [text] = _texts()
    assert '    s32 first;\n' in text
    assert text.index('s32 first;') < text.index('temp = gTable;')
    assert '    first = (*temp2);\n' in text
    assert '    temp = temp + ((*(u8 *)((s8 *)arg0 + 0xA)) * 0x510);\n' in text
    assert '    return first - (*(u16 *)((s8 *)temp + 0x418));\n' in text


def test_an_integer_base_loaded_from_a_global_as_m2c_writes_it():
    source = SOURCE.replace('    u8 *temp;', '    s32 *__base_gTable;\n    s32 temp;').replace(
        '    temp = gTable;', '    __base_gTable = &gTable;\n    temp = *__base_gTable;')
    [text] = _texts(source)
    assert '    u16 *temp2;\n    s32 first;\n' in text
    assert '    temp = temp + ((*(u8 *)((s8 *)arg0 + 0xA)) * 0x510);\n' in text
    assert '    return first - (*(u16 *)((s8 *)temp + 0x418));\n' in text


def test_a_base_read_after_the_return_declines():
    later = SOURCE.replace('    return', '    if (arg0) {\n        return', 1).replace(
        '0x418));\n}', '0x418));\n    }\n    return temp[0];\n}')
    assert _texts(later) == []
    looped = SOURCE.replace('    return', '    while (arg0) {\n        arg0 = 0;\n    }\n    if (arg1) {\n        return', 1
                            ).replace('0x418));\n}', '0x418));\n    }\n    return 0;\n}')
    assert _texts(looped) == []


def test_no_earlier_sum_declines():
    assert _texts(SOURCE.replace('(temp + ((*(u8 *)((s8 *)arg1', '(temp2 + ((*(u8 *)((s8 *)arg1')) == []


def test_a_call_a_non_integer_or_a_second_use_of_the_base_declines():
    assert _texts(SOURCE.replace('s32 cmp', 'f32 cmp')) == []
    assert _texts(SOURCE.replace('(*(u8 *)((s8 *)arg0 + 0xA))', 'f(arg0)')) == []
    assert _texts(SOURCE.replace('+ 0x418));\n}', '+ temp[1]));\n}')) == []


def test_other_operators_and_fresh_names():
    assert len(_texts(SOURCE.replace(') - (*(u16', ') + (*(u16'))) == 1
    named = _texts(SOURCE.replace('temp2', 'first'))
    assert named and 's32 first_;' in named[0]


def test_declares_itself():
    from decomprepair import registry
    assert 'last_read_base_reassign' in {f for entry in registry.declared() for f in entry.families}
