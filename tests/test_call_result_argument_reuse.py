import re

from decomprepair import registry
from decomprepair.call_result_argument_reuse import FAMILY, variants

SOURCE = """extern s32 lookup(s32 key, s32 mode);
extern void use(s32 v);
void run(s32 *table, s32 i) {
    s32 key;
    s32 id;

    key = table[i];
    if (key != -1) {
        id = lookup(key, 2);
        if (id != -1) {
            use(id);
        } else {
            use(0);
        }
    }
}
"""


def test_the_result_goes_back_into_the_argument_local():
    [(family, child)] = variants(SOURCE, 'run')
    assert family == FAMILY
    assert 'key = lookup(key, 2);' in child
    assert 'if (key != -1) {\n            use(key);' in child
    assert 's32 id;' not in child
    assert not re.search(r'\bid\b', child)
    assert variants(child, 'run') == []


def test_declines_when_the_argument_is_read_after_the_call():
    assert variants(SOURCE.replace('use(0);', 'use(key);'), 'run') == []


def test_declines_when_the_result_is_assigned_again_or_read_before():
    assert variants(SOURCE.replace('use(0);', 'id = 3;'), 'run') == []
    assert variants(SOURCE.replace('key = table[i];', 'key = table[i];\n    id = 0;'), 'run') == []


def test_declines_when_the_types_differ_or_the_argument_was_never_assigned():
    assert variants(SOURCE.replace('s32 id;', 'u8 id;'), 'run') == []
    assert variants(SOURCE.replace('key = table[i];', 'use(i);'), 'run') == []


def test_declines_when_the_argument_is_first_read_before_it_is_set():
    assert variants(SOURCE.replace('key = table[i];', 'use(key);\n    key = table[i];'), 'run') == []


def test_a_second_call_is_a_second_child():
    source = SOURCE.replace('    }\n}\n', '    }\n    key = table[0];\n    id = lookup(key, 3);\n    use(id);\n}\n')
    assert len(variants(source, 'run')) == 0  # the result is assigned twice
    source = SOURCE.replace('s32 id;', 's32 id;\n    s32 id2;').replace(
        '    }\n}\n', '    }\n    key = table[0];\n    id2 = lookup(key, 3);\n    use(id2);\n}\n')
    assert len(variants(source, 'run')) == 1  # `key` is read after the first call


def test_registry_declares_the_family():
    assert any(FAMILY in repair.families for repair in registry.declared())


def test_a_volatile_global_outside_the_function_and_a_register_hint_do_not_decline_it():
    source = 'extern volatile s32 g;\n' + SOURCE.replace('    s32 key;', '    register s32 key;')
    [(family, child)] = variants(source, 'run')
    assert 'key = lookup(key, 2);' in child and 'register' not in child
    assert variants(SOURCE.replace('s32 key;', 'volatile s32 key;'), 'run') == []
