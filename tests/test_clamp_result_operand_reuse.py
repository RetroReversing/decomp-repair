import re

from decomprepair import registry
from decomprepair.clamp_result_operand_reuse import FAMILY, variants

SOURCE = """extern void play(s32 key, s32 velocity);
void note(u8 *event, s32 shift) {
    s32 key;
    s32 key_out;

    key = event[2];
    key = key + shift;
    if (key < 0x80) {
        key_out = key & ((~key) >> 31);
    } else {
        key_out = 0x7F;
    }
    play(key_out & 0xFF, 0x40);
}
"""


def test_the_clamp_is_written_back_into_the_operand():
    [(family, child)] = variants(SOURCE, 'note')
    assert family == FAMILY
    assert 'key = (key < 0x80) ? (key & ((~key) >> 31)) : (0x7F);' in child
    assert 'play(key & 0xFF, 0x40);' in child
    assert not re.search(r'key_out', child)
    assert variants(child, 'note') == []


def test_braces_are_optional():
    plain = SOURCE.replace('{\n        key_out = key & ((~key) >> 31);\n    } else {\n        key_out = 0x7F;\n    }',
                           '\n        key_out = key & ((~key) >> 31);\n    else\n        key_out = 0x7F;')
    assert len(variants(plain, 'note')) == 1


def test_declines_when_the_operand_is_read_afterwards():
    assert variants(SOURCE.replace('play(key_out & 0xFF, 0x40);', 'play(key_out & 0xFF, key);'), 'note') == []


def test_declines_when_the_result_is_set_elsewhere_or_read_before():
    assert variants(SOURCE.replace('key = event[2];', 'key = event[2];\n    key_out = 1;'), 'note') == []
    assert variants(SOURCE.replace('play(key_out & 0xFF, 0x40);', 'play(key_out & 0xFF, 0x40);\n    key_out = 2;'), 'note') == []


def test_declines_when_the_types_differ_or_the_operand_is_not_set_first():
    assert variants(SOURCE.replace('s32 key_out;', 'u8 key_out;'), 'note') == []
    assert variants(SOURCE.replace('key = event[2];\n    key = key + shift;', 'play(key, 0);\n    key = key + shift;'), 'note') == []


def test_a_result_the_arms_use_to_compute_itself_is_declined():
    assert variants(SOURCE.replace('key_out = 0x7F;', 'key_out = key_out + 1;'), 'note') == []


def test_registry_declares_the_family():
    assert any(FAMILY in repair.families for repair in registry.declared())
