from decomprepair.byte_slot_index_stage import variants

SOURCE = '''
typedef signed int s32;
extern unsigned char table[];
extern char slots[];
void f(s32 arg) {
    s32 *p;
    if (arg) {
    one:
        p = (*(table + ((arg & 0xFFFF) * 0x64)) * 4) + slots;
    } else {
    two:
        p = (*(table + ((arg & 0xFFFF) * 0x64)) * 4) + slots;
    }
    use(p);
}
'''


def test_stages_each_and_both_reads_with_promoted_type():
    children = variants(SOURCE, 'f')
    assert len(children) == 3
    text = children[-1][1]
    assert '__typeof__(*table + 0) __repair_slot_index;' in text
    assert text.count('__repair_slot_index = *(table + ((arg & 0xFFFF) * 0x64));') == 2
    assert text.count('p = (__repair_slot_index * 4) + slots;') == 2


def test_rejects_unbraced_control_and_shadowed_tables():
    source = SOURCE.replace('    one:\n', '    one:\n        if (arg)\n')
    assert all('one:\n        if (arg)\n        __repair_slot_index' not in x for _, x in variants(source, 'f'))
    source = SOURCE.replace('    s32 *p;', '    s32 *p;\n    { int x, table; use(table); }')
    assert variants(source, 'f') == []
    assert variants(SOURCE.replace('extern unsigned char table[];', 'extern volatile unsigned char table[];'), 'f') == []
    assert variants(SOURCE + '\nint line = __LINE__;\n', 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define table other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []


def test_rejects_cpp_overload_context():
    assert variants(SOURCE + '\nclass C {};\n', 'f') == []
