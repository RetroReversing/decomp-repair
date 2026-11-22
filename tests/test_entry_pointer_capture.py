from decomprepair import entry_pointer_capture as repair

SOURCE = '''
extern s8 state;
inline static s8 read_slot(char *obj, int offset) {
    return *((s8 *) (obj + offset));
}
void f(void *arg) {
    struct { void *object; } frame;
    void *actor;
    int slot;
    do {
        frame.object = *((void **) (((char *) arg) + 0x20));
        actor = *((void **) (((char *) arg) + 0x6C));
        slot = read_slot((char *) actor, 0x182);
    } while (0);
    if (state == 0) {
        dispatch(frame.object, actor, slot);
    }
}
'''

ROWS = [
    'lw $t0, 0x20($s2)',
    'lw $s1, 0x6c($s2)',
    'lui $v0, %hi(state)',
    'lb $v0, %lo(state)($v0)',
    'sw $t0, 0x64($sp)',
    'lb $s4, 0x182($s1)',
]


def asm(rows):
    return '\n'.join(f'/* {index*4:06X} {0x80000000+index*4:08X} 00000000 */ {op}'
                     for index, op in enumerate(rows))


def test_captures_entry_state_before_storing_the_frame_pointer():
    [(_, candidate)] = repair.variants(SOURCE, 'f', asm(ROWS))
    assert 's32 entry_mode;' in candidate
    assert 'entry_road = *((void **)' in candidate
    assert candidate.index('entry_mode = state;') < candidate.index('frame.object = entry_road;')
    assert candidate.index('frame.object = entry_road;') < candidate.index('slot = read_slot')
    assert 'if (entry_mode == 0)' in candidate


def test_requires_the_target_to_store_the_loaded_pointer_after_the_mode():
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:3] + ROWS[4:5] + ROWS[3:4] + ROWS[5:]))
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:4] + ['sw $a0, 0x64($sp)'] + ROWS[5:]))


def test_skips_nontrivial_helpers_and_nonentry_regions():
    helper = SOURCE.replace('    return *((s8 *)', '    update();\n    return *((s8 *)')
    body = SOURCE.replace('    do {', '    work();\n    do {')
    shared = SOURCE.replace('    struct { void *object; } frame;', '').replace(
        'extern s8 state;', 'extern s8 state;\nextern struct { void *object; } frame;')
    assert not repair.variants(helper, 'f', asm(ROWS))
    assert not repair.variants(body, 'f', asm(ROWS))
    assert not repair.variants(shared, 'f', asm(ROWS))
