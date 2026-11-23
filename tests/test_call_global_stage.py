"""A global word passed to a call, read into a local on the line before (a probe handler, 700 -> 280)."""
from decomprepair import registry
from decomprepair.call_global_stage import FAMILY, variants

SOURCE = """extern s32 gMessageFlags;
extern s32 gOther;
extern u8 gTable[];
void show(s32, s32, char *, s32);
void handler(char *text, s32 mode)
{
  s32 extra;
  if (mode != 0)
  {
    show(0, gMessageFlags, text, -1);
  }
  extra = gOther;
  show(0, gMessageFlags, text, extra);
  show(gOther, mode, text, gTable[0]);
}
"""


def children(source=SOURCE, header=''):
    return [text for family, text in variants(source, 'handler', header) if family == FAMILY]


def test_each_call_with_a_global_gets_a_staged_local_and_one_child_does_all():
    first, second, third, both = children()
    assert '    gMessageFlags_stage = gMessageFlags;\n    show(0, gMessageFlags_stage, text, -1);' in first
    assert 'show(0, gMessageFlags, text, extra);' in first
    assert '  gMessageFlags_stage = gMessageFlags;\n  show(0, gMessageFlags_stage, text, extra);' in second
    assert '  gOther_stage = gOther;\n  show(gOther_stage, mode, text, gTable[0]);' in third
    assert 's32 gMessageFlags_stage;' in first
    assert both.count('gMessageFlags_stage') == 5 and both.count('s32 gMessageFlags_stage;') == 1
    assert both.count('gOther_stage') == 3


def test_an_argument_that_writes_or_calls_keeps_the_call_as_it_is():
    for impure in ('next()', 'extra = 1', 'extra++'):
        blocked = children(SOURCE.replace('show(0, gMessageFlags, text, -1);', f'show(0, gMessageFlags, text, {impure});'))
        assert len(blocked) == 3 and all(f'show(0, gMessageFlags_stage, text, {impure})' not in text for text in blocked)


def test_locals_parameters_arrays_and_volatile_words_are_not_staged():
    local = SOURCE.replace('  s32 extra;', '  s32 extra;\n  s32 gOther;')
    assert all('gOther_stage' not in text for text in children(local))
    assert not children('extern volatile s32 gMessageFlags;\nvoid show(s32, s32);\nvoid handler(s32 mode)\n{\n  show(0, gMessageFlags);\n}\n')
    array = SOURCE.replace('show(gOther, mode, text, gTable[0]);', 'show(gTable[0], mode, text, 1);')
    assert len(children(array)) == 3


def test_a_call_that_is_not_a_statement_of_a_block_is_left_alone():
    nested = SOURCE.replace('    show(0, gMessageFlags, text, -1);', '    extra = show2(0, gMessageFlags, text, -1);')
    assert len(children(nested)) == 3


def test_a_header_declaration_counts_and_the_registry_runs_the_module():
    source = SOURCE.replace('extern s32 gMessageFlags;\n', '')
    assert len(children(source, 'extern s32 gMessageFlags;\n')) == 4
    assert FAMILY in {family for rep in registry.declared() for family in rep.families}
