from decomprepair import arm_symbol_copy_tail as copy_tail
from decomprepair import command_post_increment as post

SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern void *gList;
extern s32 gFlag;
extern s32 gA;
extern s32 gB;
extern s32 gOut;
typedef struct {
    char pad0[0x4];
    s32 m4;
    s32 m8;
} Rec;

s32 f(s32 arg0) {
    s32 *src;
    s32 first;
    void *cmd;

    if (gFlag == 0) {
        cmd = gList;
        gList += 8;
        M2C_FIELD(cmd, s32 *, 0) = 1;
        first = gA;
        src = &gA;
    } else {
        cmd = gList;
        gList += 8;
        M2C_FIELD(cmd, s32 *, 0) = 2;
        first = gB;
        src = &gB;
    }
    M2C_FIELD(&gOut, s32 *, 0) = first;
    M2C_FIELD(&gOut, s32 *, 4) = (s32) (((Rec *) src)->m4);
    M2C_FIELD(&gOut, s32 *, 8) = (s32) (((Rec *) src)->m8);
    return arg0;
}
'''


def test_the_merged_copy_is_written_in_both_arms_from_the_symbols():
    children = copy_tail.variants(SOURCE, 'f')
    child = children[0][1]
    body = child[child.index('s32 f('):]
    assert 'first =' not in body and 'src =' not in body
    assert body.count('M2C_FIELD(&gOut, s32 *, 0) =') == 2
    assert 'M2C_FIELD(&gOut, s32 *, 0) = gA;' in body and 'M2C_FIELD(&gOut, s32 *, 0) = gB;' in body
    assert '(s32) (M2C_FIELD((&gA), s32 *, 0x4));' in body
    assert '(s32) (M2C_FIELD((&gB), s32 *, 0x8));' in body
    assert body.rstrip().endswith('}\n    return arg0;\n}')
    # the second child keeps the record members
    assert '((Rec *) (&gA))->m4' in children[1][1]


def test_a_value_read_after_the_first_store_is_left_alone():
    moved = SOURCE.replace('''    M2C_FIELD(&gOut, s32 *, 0) = first;
    M2C_FIELD(&gOut, s32 *, 4) = (s32) (((Rec *) src)->m4);
''', '''    M2C_FIELD(&gOut, s32 *, 4) = (s32) (((Rec *) src)->m4);
    M2C_FIELD(&gOut, s32 *, 0) = first;
''')
    assert copy_tail.variants(moved, 'f') == []


def test_a_pointer_read_elsewhere_is_left_alone():
    assert copy_tail.variants(SOURCE.replace('return arg0;', 'return *src;'), 'f') == []


def test_the_advance_becomes_a_post_increment():
    ((family, child),) = post.variants(SOURCE, 'f')
    assert family == 'command_post_increment'
    assert child.count('cmd = (*(M2CCommandPair **) &gList)++;') == 2
    assert 'gList += 8' not in child
    assert child.index('} M2CCommandPair;') < child.index('s32 f(')


def test_a_word_pointer_is_not_stepped_by_eight_bytes():
    assert post.variants(SOURCE.replace('extern void *gList;', 'extern s32 *gList;'), 'f') == []
