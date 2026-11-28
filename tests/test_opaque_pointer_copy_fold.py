"""A shared pointer's copies may be removed only when they remain stable."""
import pytest

from decomprepair.opaque_pointer_copy_fold import FAMILY, variants

SOURCE = '''void use(void *); void emit(void *);
void f(void *p) {
    void *root;
    void *first;
    void *second;
    root = p;
    first = root; do { second = root; } while (0);
    use(first); use(first); emit(second);
}
'''


def test_fold_both_copies_and_offer_individual_children():
    result = variants(SOURCE, 'f')
    assert len(result) == 3 and all(family == FAMILY for family, _ in result)
    combined = result[0][1]
    assert 'first' not in combined and 'second' not in combined
    assert combined.count('use(root)') == 2 and 'emit(root)' in combined
    assert 'while (0)' not in combined


@pytest.mark.parametrize('change', [
    lambda s: s.replace('first = root;', 'if (p) first = root;'),
    lambda s: s.replace('first = root;', 'if (p) { first = root; }'),
    lambda s: s.replace('use(first); use(first);', 'root = p; use(first); use(first);'),
    lambda s: s.replace('use(first); use(first);', 'escape(&root); use(first); use(first);'),
    lambda s: s.replace('use(first); use(first);', 'escape(&first); use(first); use(first);'),
    lambda s: s.replace('use(first); use(first);', 'first = p; use(first); use(first);'),
    lambda s: s.replace('use(first); use(first);', 'goto label; label: use(first); use(first);'),
    lambda s: s.replace('void *first;', 'void * volatile first;'),
    lambda s: s.replace('use(first); use(first);', '{\nvoid *first;\nuse(first);\n} use(first);'),
    lambda s: s.replace('use(first); use(first);', '{\nint first;\nuse(first);\n} use(first);'),
    lambda s: s.replace('use(first); use(first);', '{ int first; use(first); } use(first);'),
    lambda s: '#define READ_FIRST first\n' + s,
])
def test_unsafe_first_alias_is_not_folded(change):
    for _, child in variants(change(SOURCE), 'f'):
        assert 'void *first;' in child or 'void * volatile first;' in child
        assert 'use(first)' in child


def test_dependent_copies_are_not_combined_into_an_undefined_local():
    source = SOURCE.replace('second = root;', 'second = first;')
    assert all('first' in child or 'second' in child for _, child in variants(source, 'f'))


def test_nested_function_cannot_hide_a_later_source_mutation():
    source = SOURCE.replace('root = p;', 'void change(void) { root = p; } root = p;')
    assert not variants(source.replace('use(first);', 'change(); use(first);', 1), 'f')


def test_macro_argument_cannot_mutate_a_folded_copy_or_source():
    header = '#define CHANGE(x) ((x) = 0)\n'
    for name in ('first', 'root'):
        source = SOURCE.replace('use(first);', f'CHANGE({name}); use(first);', 1)
        for _, child in variants(source, 'f', header):
            assert 'void *first;' in child and 'use(first)' in child


def test_unused_macro_does_not_block_the_fold():
    assert variants(SOURCE, 'f', '#define UNRELATED(x) ((x) + 1)\n')


def test_macro_cannot_retain_source_address_before_the_copy():
    source = SOURCE.replace('first = root;', 'SAVE(root); first = root;')
    header = '#define SAVE(x) remember(&(x))\n'
    assert not variants(source, 'f', header)


def test_unknown_includes_are_not_assumed_to_be_macro_free():
    assert not variants(SOURCE, 'f', '#include "unknown.h"\n')
    assert not variants(SOURCE, 'f', '#include_next "unknown.h"\n')
    assert not variants(SOURCE, 'f', '#import "unknown.h"\n')


def test_command_line_macros_are_not_assumed_to_be_safe():
    assert not variants(SOURCE, 'f', flags=['-O2', '-DCHANGE(x)=((x)=0)'])
    assert not variants(SOURCE, 'f', flags=['-O2', '-D', 'CHANGE(x)=((x)=0)'])
    assert not variants(SOURCE, 'f', flags=['@flags.rsp'])
    assert variants(SOURCE, 'f', flags=['-O2', '-G0'])
    for option in ('-include', '-imacros=other.h', '-Wp,-DCHANGE(x)=0', '-Xpreprocessor'):
        assert not variants(SOURCE, 'f', flags=['-O2', option])


def test_member_name_equal_to_origin_is_not_a_local_reassignment():
    source = SOURCE.replace('emit(second);', 'obj.root = second; emit(second);')
    assert 'first' not in variants(source, 'f')[0][1]
