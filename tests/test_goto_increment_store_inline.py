from decomprepair import registry
from decomprepair.goto_increment_store_inline import variants

SOURCE = '''
typedef signed int s32;
void f(int choice) {
    s32 *p;
    s32 value;
    s32 one;
    if (choice) {
        one = *p + 1;
        value = one;
        goto store;
    } else {
        value = *p;
        value += 1;
        goto store;
    }
store:
    *p = value;
after:
    return;
}
'''


def test_inlines_both_arms_as_one_child():
    result = variants(SOURCE, 'f')
    assert len(result) == 1
    family, text = result[0]
    assert family == 'goto_increment_store_inline'
    assert text.count('{ *p = value; goto after; }') == 2
    assert 'store:\n    *p = value;\nafter:' in text
    assert any(entry.module.endswith('goto_increment_store_inline') for entry in registry.declared())


def test_preserves_single_statement_if_body():
    source = SOURCE.replace('        goto store;', '        if (choice) goto store;', 1)
    result = variants(source, 'f')
    # The conditional jump remains conditional because the replacement is a block.
    assert not result or 'if (choice) { *p = value; goto after; }' in result[0][1]


def test_declines_unsafe_or_incomplete_context():
    assert not variants(SOURCE.replace('after:', 'do_something();\nafter:'), 'f')
    assert not variants(SOURCE.replace('        goto store;', '        goto after;', 1), 'f')
    assert not variants(SOURCE.replace('    s32 value;', '    volatile s32 value;'), 'f')
    assert not variants(SOURCE.replace('    if (choice) {', '    { int value; use(value); }\n    if (choice) {'), 'f')
    assert not variants(SOURCE.replace('    if (choice) {', '    { __typeof__(value) p; use(p); }\n    if (choice) {'), 'f')
    assert not variants(SOURCE, 'f', flags=['-Dvalue=other'])
    assert not variants(SOURCE, 'f', header='#include "unknown.h"')
