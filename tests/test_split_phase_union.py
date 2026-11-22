from decomprepair.phase_union_repairs import split_variants, variants

SOURCE = """
int f(int *input, int gate) {
    union { int *pointer; int value; } __repair_phase_storage;
    __repair_phase_storage.pointer = input;
    consume(__repair_phase_storage.pointer);
    __repair_phase_storage.value = 12;
    if (gate) {
        __repair_phase_storage.value = 8;
    }
    return __repair_phase_storage.value;
}
"""


def test_splits_disjoint_initialized_members_via_normal_adapter():
    [(family, candidate)] = [item for item in variants(SOURCE, 'f', 'mips', ['-mgp32'])
                             if item[0] == 'split_pointer_integer_phase']
    assert family == 'split_pointer_integer_phase'
    assert 'int * __repair_phase_storage_pointer; int __repair_phase_storage_value;' in candidate
    assert 'return __repair_phase_storage_value;' in candidate


def test_rejects_union_aliases_and_reads_without_live_member():
    for text in (
        SOURCE.replace('consume(__repair_phase_storage.pointer);',
                       'consume(&(__repair_phase_storage.pointer));'),
        SOURCE.replace('return __repair_phase_storage.value;',
                       'return *__repair_phase_storage.pointer;'),
        SOURCE.replace('__repair_phase_storage.value = 12;', ''),
        '#define consume(p) retain_address(&(p))\n' + SOURCE,
    ):
        assert split_variants(text, 'f', 'mips') == []
