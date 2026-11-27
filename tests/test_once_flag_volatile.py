"""A set-once init flag declared `volatile` (a gcc 2.8.1 device-manager start-up)."""
from decomprepair import once_flag_volatile as t

SOURCE = '''extern s32 sStarted;
extern u8 sQueue[];
void f(s32 pri)
{
    if (sStarted == 0) {
        sStarted = 1;
        create(sQueue, pri);
    }
}
'''


def test_the_init_flag_is_declared_volatile():
    assert [text for _, text in t.variants(SOURCE, 'f')] == [SOURCE.replace('extern s32', 'extern volatile s32')]


def test_an_early_return_guard_counts():
    source = SOURCE.replace('if (sStarted == 0) {', 'if (sStarted != 0) {\n        return;\n    }\n    {')
    assert len(t.variants(source, 'f')) == 1


def test_volatile_untested_or_unset_globals_are_left_alone():
    assert t.variants(SOURCE.replace('extern s32', 'extern volatile s32'), 'f') == []
    assert t.variants(SOURCE.replace('sStarted == 0', 'pri == 0'), 'f') == []
    assert t.variants(SOURCE.replace('sStarted = 1;', 'g(sStarted);'), 'f') == []
