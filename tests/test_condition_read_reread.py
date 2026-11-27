import re

from decomprepair.condition_read_reread import FAMILY, variants

SOURCE = """void step(u8 player) {
    u16 buttons;

    if (player == 1) {
        buttons = **gPad;
        if (buttons & code[gStep]) {
            gStep++;
            if (gStep == 10) {
                gDone = 1;
                gStep = 0;
                play(5);
            }
        } else if (buttons & 0xFFFF) {
            gStep = 0;
        }
    }
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_the_read_replaces_the_local_in_both_tests():
    family, text = variants(SOURCE, 'step')[0]
    flat = _flat(text)
    assert family == FAMILY
    assert 'buttons' not in flat
    assert 'if ((**gPad) & code[gStep]) {' in flat
    assert '} else if (**gPad) {' in flat   # the redundant halfword mask goes


def test_nothing_when_a_store_or_a_call_stands_between_the_read_and_a_test():
    stored = SOURCE.replace('buttons = **gPad;', 'buttons = **gPad;\n        gSeen = 1;')
    called = SOURCE.replace('buttons = **gPad;', 'buttons = **gPad;\n        poll();')
    assert variants(stored, 'step') == []
    assert variants(called, 'step') == []


def test_nothing_for_a_word_local_a_single_test_or_a_value_use():
    assert variants(SOURCE.replace('u16 buttons;', 's32 buttons;'), 'step') == []
    assert variants(SOURCE.replace('else if (buttons & 0xFFFF)', 'else if (gOther)'), 'step') == []
    assert variants(SOURCE.replace('gDone = 1;', 'gDone = buttons;'), 'step') == []


def test_every_web_at_once_then_each_alone():
    twice = SOURCE.replace('    }\n}\n', """    }
    if (player == 2) {
        buttons = **gPad;
        if (buttons & code[gStep]) {
            gStep++;
        } else if (buttons) {
            gStep = 0;
        }
    }
}
""")
    children = [text for _, text in variants(twice, 'step')]
    assert len(children) == 3
    assert 'buttons' not in children[0]
    assert all('u16 buttons;' in child for child in children[1:])
