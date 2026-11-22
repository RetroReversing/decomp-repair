from decomprepair.switch_tables import relabeled

SOURCE = '''
void f(int x) {
    switch (x) {
        case 0x64: first(); return;
        case 0x65: second(); return;
        case 0x66: third(); return;
        case 0x67: fourth(); return;
        case 0x6C: return;
    }
    fallback();
}
'''
COMPILED = [56, 80, 104, 216, 284, 284, 284, 284, 304]
TARGET = [80, 104, 284, 216, 284, 284, 284, 284, 56]


def test_case_labels_follow_the_measured_destination_tables():
    proposal, = relabeled(SOURCE, 'f', 100, COMPILED, TARGET, 284)
    assert proposal[0] == 'verified_switch_labels'
    result = proposal[1]
    assert 'case 0x6C: first(); return;' in result
    assert 'case 0x64: second(); return;' in result
    assert 'case 0x65: third(); return;' in result
    assert 'case 0x67: fourth(); return;' in result
    assert 'case 0x66: break;' in result
    assert 'fallback();' in result


def test_case_label_recovery_rejects_ambiguous_or_unsafe_evidence():
    assert not relabeled(SOURCE, 'f', 100, COMPILED[:-1], TARGET, 284)
    assert not relabeled(SOURCE, 'f', 100, COMPILED, TARGET, 999)
    assert not relabeled(SOURCE, 'f', 100, COMPILED, [999, *TARGET[1:]], 284)
    assert not relabeled(SOURCE.replace('case 0x6C: return;', 'case 0x6C: side_effect(); return;'),
                         'f', 100, COMPILED, TARGET, 284)
    assert not relabeled(SOURCE.replace('case 0x65: second(); return;', 'case 0x65: case 0x66: second(); return;'),
                         'f', 100, COMPILED, TARGET, 284)
    assert not relabeled(SOURCE.replace('case 0x64:', 'case SOME_MACRO:'), 'f', 100, COMPILED, TARGET, 284)
    assert not relabeled(SOURCE.replace('case 0x6C: return;', 'default: return;'), 'f', 100, COMPILED, TARGET, 284)
    assert not relabeled(SOURCE.replace('first(); return;', 'first();'), 'f', 100, COMPILED, TARGET, 284)

