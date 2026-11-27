from decomprepair.absent_call_drop import FAMILY, REPAIR, variants

SOURCE = """s32 count_files(void *);
s32 check(void *);
s32 read_entry(void *, s32);
s32 get_status(void *);
s32 count(u8 *p, s32 *out)
{
    s32 ret;
    s32 i;
    ret = check(p);
    if (ret == 0) {
        for (i = 0; i < 16; i++) {
            ret = read_entry(p, i);
        }
        *out = i;
        ret = get_status(p);
    }
    return ret;
}
"""
ASM = """glabel count
 jal check
 nop
 jal read_entry
 nop
"""


def _found(source=SOURCE, asm=ASM, name='count', header=''):
    return [text for family, text in variants(source, name, asm, header) if family == FAMILY]


def test_a_call_the_target_never_makes_before_the_return_becomes_return_zero():
    returned, zeroed = _found()
    assert '        *out = i;\n        return 0;\n    }\n    return ret;' in returned
    assert '        *out = i;\n        ret = 0;\n    }\n    return ret;' in zeroed
    assert 'get_status(p)' not in returned + zeroed


def test_calls_the_target_makes_are_kept():
    assert not _found(asm=ASM + ' jal get_status\n')


def test_a_stale_name_with_an_unclaimed_target_is_left_to_the_rename():
    assert not _found(asm=ASM + ' jal new_status_name\n')


def test_a_tail_inside_a_loop_does_not_return():
    source = SOURCE.replace('ret = read_entry(p, i);', 'ret = get_status(p);').replace(
        '        *out = i;\n        ret = get_status(p);\n', '')
    (text,) = _found(source)
    assert 'ret = 0;' in text and 'return 0;' not in text


def test_a_return_of_the_call_and_a_bare_call_and_a_nested_one():
    source = """void log_line(s32);
s32 pick(s32);
s32 count(s32 a)
{
    log_line(a);
    if (a > pick(a)) {
        return pick(a + 1);
    }
    return a;
}
"""
    asm = 'glabel count\n jal check\n nop\n jal other\n nop\n'
    logged, picked, both = _found(source, asm)
    assert 'log_line(a);' not in logged.split('count(')[1] and 'pick(a)' in logged
    assert 'if (a > 0)' in picked and 'return 0;' in picked
    assert '(a)' not in both.split('{', 1)[1]


def test_effects_in_arguments_macros_and_inline_builtins_are_left_alone():
    source = """#define FIELD(p) (*(s32 *) (p))
f32 sqrtf(f32);
void note(s32);
s32 count(s32 a)
{
    note(a++);
    FIELD(a) = sqrtf(a);
    return a;
}
"""
    assert not _found(source, 'glabel count\n jal check\n nop\n')


def test_nothing_without_the_target_assembly():
    assert not _found(asm='')
    assert REPAIR['needs'] == ('source', 'name', 'asm', 'header')
