import re

from decomprepair.switch_goto_tail_arms import FAMILY, REPAIR, variants

SOURCE = """void pause(void)
{
    s32 a;
    s32 v;
    switch (gFlag) {
        case 0: a = 0xA; goto lookup;
        default: a = 0x2E4; goto lookup;
        case 1: v = look(0x2E2); goto format;
        case 2: v = look(0x2E3); goto format;
    }
    lookup: v = look(a) & 0xFF;
    format: show(gTarget, v);
    gDone = 1;
    finish();
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_each_goto_becomes_the_run_it_reached_up_to_the_last_phi_use():
    found = [_flat(t) for f, t in variants(SOURCE, 'pause') if f == FAMILY]
    assert len(found) == 3
    out = found[0]
    assert 'case 0: a = 0xA; v = look(a) & 0xFF; show(gTarget, v); break;' in out
    assert 'case 1: v = look(0x2E2); show(gTarget, v); break;' in out
    assert 'lookup:' not in out and 'format:' not in out and 'goto' not in out
    assert out.index('gDone = 1;') > out.index('default:')


def test_nothing_when_a_goto_leaves_the_labels_or_another_goto_reaches_them():
    assert variants(SOURCE.replace('goto format;', 'goto elsewhere;', 1), 'pause') == []
    other = SOURCE.replace('gDone = 1;', 'if (gX) goto lookup;\n    gDone = 1;')
    assert variants(other, 'pause') == []


def test_it_works_inside_a_do_while_fence():
    fenced = SOURCE.replace('    switch', '    do { switch').replace('    finish();', '    finish(); } while (0);')
    found = [_flat(t) for f, t in variants(fenced, 'pause')]
    assert found and 'case 1: v = look(0x2E2); show(gTarget, v); break;' in found[0]


def test_it_declares_itself():
    assert REPAIR['variants'] is variants


def test_a_second_child_writes_each_arms_temporaries_into_the_call():
    found = [_flat(t) for f, t in variants(SOURCE, 'pause')]
    assert len(found) == 3
    assert 'case 1: show(gTarget, look(0x2E2)); break;' in found[1]


def test_a_third_child_drops_the_mask_on_a_call_result():
    found = [_flat(t) for f, t in variants(SOURCE, 'pause')]
    assert len(found) == 3 and 'case 0: show(gTarget, look(0xA)); break;' in found[2]
