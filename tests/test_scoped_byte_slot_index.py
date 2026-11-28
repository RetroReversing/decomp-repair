from decomprepair.scoped_byte_slot_index import variants

SOURCE = '''
typedef signed int s32;
extern unsigned char table[];
extern char slots[];
void f(s32 arg) {
    s32 *p;
    if (arg)
        p = (*(table + ((arg & 0xFFFF) * 100)) * 4) + slots;
    else
        p = (*(table + ((arg & 0xFFFF) * 100)) * 4) + slots;
    use(p);
}
'''


def test_stages_each_and_both_without_changing_control():
    children = variants(SOURCE, 'f')
    assert len(children) == 3
    text = children[-1][1]
    assert text.count('__typeof__(*table + 0) __repair_scoped_index;') == 2
    assert text.count('__typeof__(slots + 0) __repair_scoped_base;') == 2
    assert text.count('p = (__repair_scoped_index * 4) + __repair_scoped_base;') == 2
    assert 'if (arg)\n        {' in text and 'else\n        {' in text


def test_rejects_side_effects_and_volatile():
    assert variants(SOURCE.replace('arg & 0xFFFF', 'arg++ & 0xFFFF'), 'f') == []
    assert variants(SOURCE.replace('extern char slots[];', 'extern volatile char slots[];'), 'f') == []
    assert variants(SOURCE.replace('s32 *p;', 's32 *p;\n    int __repair_scoped_index;'), 'f') == []
    assert variants(SOURCE + '\nclass C {};\n', 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define table other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []
