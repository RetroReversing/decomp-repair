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


def test_member_name_equal_to_origin_is_not_a_local_reassignment():
    source = SOURCE.replace('emit(second);', 'obj.root = second; emit(second);')
    assert 'first' not in variants(source, 'f')[0][1]
