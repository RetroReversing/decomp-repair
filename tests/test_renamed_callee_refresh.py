import re

from decomprepair.renamed_callee_refresh import FAMILY, REPAIR, variants

SOURCE = """s32 emit_projection_viewport_commands();
s32 drawBeam();
void actor(u8 *a)
{
    emit_projection_viewport_commands();
    drawBeam(a);
    gRenderMode = 0;
    if (a[0]) {
        emit_projection_viewport_commands();
    }
}
"""
ASM = """glabel actor
 jal appendProjectionViewportCommands
 nop
 jal drawBeam
 nop
 jal appendProjectionViewportCommands
 nop
"""


def _found(source=SOURCE, asm=ASM, name='actor'):
    return [text for family, text in variants(source, name, asm) if family == FAMILY]


def test_a_stale_callee_takes_the_name_the_target_calls_everywhere_including_its_prototype():
    (text,) = _found()
    assert 'emit_projection_viewport_commands' not in text
    assert len(re.findall(r'appendProjectionViewportCommands', text)) == 3


def test_a_name_the_target_already_calls_is_not_stale():
    assert not _found(asm=ASM.replace('appendProjectionViewportCommands', 'emit_projection_viewport_commands'))


def test_equal_counts_with_two_candidates_are_not_guessed():
    asm = ASM.replace('jal drawBeam', 'jal otherName\n nop\n jal thirdName').replace('otherName', 'x1')
    source = SOURCE.replace('drawBeam(a)', 'oldTwo(a); oldThree(a)').replace('s32 drawBeam();', '')
    assert not [t for f, t in variants(source, 'actor', asm) if 'x1' in t]


def test_a_name_the_assembly_uses_as_data_or_a_function_defined_in_the_source_is_left_alone():
    assert not _found(asm=ASM + ' lui $a0, %hi(emit_projection_viewport_commands)\n')
    helper = 'static s32 emit_projection_viewport_commands(void) { return 1; }\n' + SOURCE
    assert not _found(source=helper)


def test_a_name_the_source_already_uses_is_never_overwritten():
    assert not _found(source=SOURCE + 'void other() { appendProjectionViewportCommands(); }\n')


def test_it_is_declared_for_the_registry():
    assert REPAIR['variants'] is variants and 'asm' in REPAIR['needs']
