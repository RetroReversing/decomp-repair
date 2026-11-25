"""The entry web of a local reused inside the loop, given its own local (an N64 audio thread, SN64 GCC 2.8.1)."""
from decomprepair.entry_web_split import FAMILY, variants

SOURCE = """void thread(void)
{
    s32 arg;
    s32 h;

    h = init();
    setup();
    report(fmt, h);
    for (;;) {
        arg = next();
        h = start(arg);
        use(h);
    }
}
"""


def test_the_entry_web_gets_its_own_local():
    found = variants(SOURCE, 'thread')
    assert [family for family, _ in found] == [FAMILY]
    text = found[0][1]
    assert '    s32 h;\n    s32 h_entry;\n' in text
    assert '    h_entry = init();\n    setup();\n    report(fmt, h_entry);\n' in text
    assert '        h = start(arg);\n        use(h);\n' in text


def test_a_value_live_into_the_loop_is_not_split():
    live = SOURCE.replace('        h = start(arg);\n        use(h);\n', '        use(h);\n        h = start(arg);\n')
    assert variants(live, 'thread') == []
    assert variants(SOURCE.replace('    for (;;) {', '    {'), 'thread') == []
