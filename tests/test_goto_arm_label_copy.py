"""goto_arm_label_copy: the run behind a label at the head of an `if` arm copied in place of each `goto` to it.

Shape of a 117-instruction menu function (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) at 120: the call's third
argument register was set at one call site only, so the first scheduler (sched.c `birthing_insn_p`: a hard register's
`reg_n_sets` counts the whole function) placed its setup right before the call; the block written in both cases of the
switch was exact (120 -> 0). The source below is made up; it only has that shape."""
from decomprepair import goto_arm_label_copy as copy
from decomprepair import registry

HEAD = '''extern s32 f(void *);
extern void g(s32, s32, s32);
extern s32 gMode, gA, gB;
'''

SOURCE = HEAD + '''void h(void *item, s32 draw)
{
    s32 w;
    s32 sel;
    switch (gMode) {
    case 0:
        if (draw & 0xFF) goto draw_box;
        sel = gA;
        goto check;
    case 1:
        if (draw & 0xFF) {
draw_box:
            w = (f(item) * 12) & 0xFC;
            g(1, 2, w);
            gB = 1;
            break;
        }
        sel = gB;
check:
        if (sel == 3)
            gB = 2;
        break;
    }
}
'''


def children(source):
    return [text for _, text in copy.variants(source, 'h')]


def test_the_run_is_written_in_place_of_the_goto():
    [text] = children(SOURCE)
    assert 'goto draw_box' not in text and 'draw_box:' not in text
    assert text.count('g(1, 2, w);') == 2 and text.count('w = (f(item) * 12) & 0xFC;') == 2
    first = text.index('if (draw & 0xFF) {')
    assert text.index('g(1, 2, w);') > first and text.index('break;', first) < text.index('sel = gA;')
    assert text.count('{') == text.count('}')


def test_an_unbraced_goto_gets_braces_and_the_other_arm_is_untouched():
    [text] = children(SOURCE)
    assert text.count('if (draw & 0xFF) {') == 2


def test_every_goto_alone_is_offered_too():
    two = SOURCE.replace('sel = gB;\ncheck:', 'sel = gB;\ncheck:').replace(
        '        sel = gB;\ncheck:', '        if (gA) goto draw_box;\n        sel = gB;\ncheck:')
    kids = children(two)
    assert len(kids) == 3
    assert [k.count('g(1, 2, w);') for k in kids] == [3, 2, 2]


def test_a_run_that_falls_out_is_left_alone():
    falling = SOURCE.replace('            gB = 1;\n            break;\n', '            gB = 1;\n')
    assert children(falling) == []


def test_a_break_must_stay_in_the_same_switch():
    far = HEAD + '''void h(void *item, s32 draw)
{
    s32 w;
    while (gA) {
        if (draw) goto draw_box;
        gA = 0;
    }
    switch (gMode) {
    case 1:
        if (draw & 0xFF) {
draw_box:
            w = (f(item) * 12) & 0xFC;
            g(1, 2, w);
            break;
        }
    }
}
'''
    assert children(far) == []


def test_a_label_inside_the_run_or_a_declaration_is_left_alone():
    nested = SOURCE.replace('            gB = 1;\n', '            gB = 1;\nagain:\n')
    assert children(nested) == []
    declared = SOURCE.replace('            w = (f', '            s32 t = 0;\n            w = (f')
    assert children(declared) == []


def test_it_declares_itself_to_the_registry():
    repair = registry.get('goto_arm_label_copy')
    assert repair is not None and 'goto_arm_label_copy' in repair.families
    assert registry.problems(repair) == []
