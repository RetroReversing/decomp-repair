from decomprepair import pointer_pair_loop as repairs
from decomprepair import registry

SOURCE = """\
extern u32 gCount;
extern char gSlots[];
extern char gBases[];
void emit(void *, char *, u32, u32);

s32 find(s32 want, u16 *first) {
    void *args[3];
    s32 step;
    char *cur = (char *)first;
    u32 slot = 0;
    u32 count = gCount;
    u32 key;
    char *mark;
    s32 idx, off;
    if (count) {
        step = 0;
        for (;;) {
            if (*((void **)(gSlots + step)) != cur) {
                slot++;
                step += 0xC;
                if (slot < count) continue;
            }
            break;
        }
    }
    key = *(u16 *)cur;
    if ((u16)key != 0xFFFF) {
        idx = slot * 2;
        want &= 0xFFFF;
        off = (idx + slot) * 4;
        mark = cur + 2;
    again:
        if (key == (u32)want) {
            if (*(u16 *)mark == 0) {
                s32 offset = *(s32 *)(mark + 2);
                s32 base = *(s32 *)(gBases + off);
                args[0] = cur + 0xC;
                cur += 8;
                *(s32 *)(mark + 6) = offset + base;
                emit(&args, cur, slot, key);
            }
            (*(u16 *)mark)++;
        } else {
            cur += 0x1C;
            key = *(u16 *)cur;
            mark += 0x1C;
            if (key != 0xFFFF) goto again;
        }
    }
    return 1;
}
"""


def _by_family():
    return {family: text for family, text in repairs.variants(SOURCE, 'find')}


def test_the_whole_set_is_the_first_child():
    family, text = repairs.variants(SOURCE, 'find')[0]
    assert family == 'pointer_pair_loop'
    body = text[text.index('find(s32'):]
    assert 'goto' not in body and 'again:' not in body
    assert 'mark' not in body
    assert 'u16 key;' in body and '(u16)key' not in body
    assert 'do { if (key == (u32)want)' in body and '} while (key != 0xFFFF);' in body
    assert '*(u16 *)(cur + 2) == 0' in body
    assert '*(s32 *)(cur + 4)' in body and '*(s32 *)(cur + 8) = offset + base;' in body
    assert 'emit(&args, cur + 8, slot, key);' in body
    assert 'cur += 8;' not in body and 'cur += 0x1C;' in body
    assert ' break; }' in body


def test_the_shorter_combinations_follow():
    families = [family for family, _ in repairs.variants(SOURCE, 'find')]
    assert families[0] == 'pointer_pair_loop'
    assert {'goto_match_break_loop', 'derived_pointer_fold', 'sentinel_halfword_local'} <= set(families)
    one = _by_family()
    assert 'do {' in one['goto_match_break_loop'] and 'mark' in one['goto_match_break_loop']
    assert 'goto again' in one['derived_pointer_fold'] and 'mark' not in one['derived_pointer_fold']
    assert 'u16 key;' in one['sentinel_halfword_local'] and 'goto again' in one['sentinel_halfword_local']


def test_a_step_that_cannot_move_declines_the_fold():
    # the base is read after the block it was stepped in, so the step cannot be sunk into its uses
    text = SOURCE.replace('(*(u16 *)mark)++;', '(*(u16 *)mark)++;\n            emit(&args, cur, slot, key);')
    families = [family for family, _ in repairs.variants(text, 'find')]
    assert 'derived_pointer_fold' not in families and 'pointer_pair_loop' not in families
    assert 'sentinel_halfword_local' in families
    assert 'goto_match_break_loop' in families


def test_other_loops_and_functions_are_left_alone():
    assert repairs.variants(SOURCE, 'absent') == []
    plain = 's32 f(s32 a) { s32 i; for (i = 0; i < a; i++) { a -= i; } return a; }\n'
    assert repairs.variants(plain, 'f') == []
    two_pointers = SOURCE.replace('mark += 0x1C;', 'mark += 0x2C;')
    assert 'derived_pointer_fold' not in [family for family, _ in repairs.variants(two_pointers, 'find')]


def test_the_children_still_compile_as_c_text():
    for _, text in repairs.variants(SOURCE, 'find'):
        assert text.count('{') == text.count('}')


def test_it_declares_itself():
    repair = registry.get('pointer_pair_loop')
    assert repair and registry.problems(repair) == []
