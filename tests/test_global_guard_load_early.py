from decomprepair import global_guard_load_early, registry

SOURCE = """extern s32 sState;
extern s32 sDirty;
extern s32 sBusy;
void update(void) {
    while (running()) {
        if (sState == 6) {
            sState = 1;
            sDirty = 1;
            if (sBusy == 0) {
                reload();
            }
        }
    }
}
"""


def children(source, header=''):
    return [child for _, child in global_guard_load_early.variants(source, 'update', header)]


def test_read_above_the_whole_run_of_stores_and_above_the_last():
    whole, last = children(SOURCE)
    assert '{\n    s32 staged_global0;\n' in whole
    assert ('staged_global0 = sBusy;\n            sState = 1;\n            sDirty = 1;\n'
            '            if (staged_global0 == 0) {') in whole
    assert ('sState = 1;\n            staged_global0 = sBusy;\n            sDirty = 1;\n'
            '            if (staged_global0 == 0) {') in last


def test_header_declaration_pointer_type_and_first_operand():
    source = SOURCE.replace('extern s32 sBusy;\n', '').replace('sBusy == 0', '!sBusy && ready()')
    child = children(source, 'extern Node *sBusy;\n')[0]
    assert '    Node * staged_global0;\n' in child
    assert 'if (!staged_global0 && ready()) {' in child


def test_not_past_a_call_a_pointer_store_or_a_store_to_the_tested_name():
    for blocker in ('sDirty = next();', '*cursor = 1;', 'table[0] = 1;', 'sBusy = 1;', 'p->field = 1;'):
        assert not children(SOURCE.replace('sDirty = 1;', blocker)), blocker


def test_not_for_an_array_a_volatile_or_an_undeclared_name():
    assert not children(SOURCE.replace('extern s32 sBusy;', 'extern s32 sBusy[];'))
    assert not children(SOURCE.replace('extern s32 sBusy;', 'extern volatile s32 sBusy;'))
    assert not children(SOURCE.replace('extern s32 sBusy;\n', ''))


def test_declared_to_the_registry():
    assert any(entry.module == 'global_guard_load_early' for entry in registry.declared())
