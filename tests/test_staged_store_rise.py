"""A stored value read into a block local ahead of the stores before it."""
from decomprepair import staged_store_rise as rise

HEADER = 'typedef unsigned char u8;\ntypedef unsigned short u16;\ntypedef int s32;\n'
SOURCE = '''typedef struct E { s32 owner; u16 index; u8 kind; u8 state; struct E *link; } E;
E *alloc(void);
void f(E *self) {
    E *child;
    E *first;

    child = alloc();
    first = child;
    if (child != 0) {
        child->owner = self->owner;
        child->kind = 2;
        child->state = 3;
        child->index = self->index + 2;
        child->link = self;
    }
    child = alloc();
    if (child != 0) {
        child->owner = self->owner;
        child->kind = 2;
        child->state = 3;
        child->index = self->index + 1;
        child->link = first;
    }
}
'''


def children(source):
    return [text for family, text in rise.variants(source, 'f', HEADER) if family == 'staged_store_rise']


def block(local_line, value):
    return (f'        u16 __rise;\n        child->owner = self->owner;\n{local_line}        child->kind = 2;\n'
            f'        child->state = 3;\n        child->index = __rise;\n')


def test_both_blocks_stage_the_sum_after_the_first_store():
    wanted = [text for text in children(SOURCE) if text.count('u16 __rise;') == 2
              and block('        __rise = self->index + 2;\n', 2) in text
              and block('        __rise = self->index + 1;\n', 1) in text]
    assert len(wanted) == 1


def test_each_block_alone_is_offered_too():
    assert any(text.count('u16 __rise;') == 1 and '__rise = self->index + 1;' in text for text in children(SOURCE))


def test_a_store_to_the_read_field_stops_the_move():
    source = SOURCE.replace('        child->state = 3;\n        child->index = self->index + 2;',
                            '        child->index = 0;\n        child->index = self->index + 2;')
    assert not any('__rise = self->index + 2;' in text for text in children(source))


def test_a_call_stops_the_move():
    source = SOURCE.replace('        child->state = 3;\n', '        alloc();\n')
    assert not any('__rise = self->index' in text for text in children(source))


def test_an_assigned_base_stops_the_move():
    source = SOURCE.replace('        child->state = 3;\n', '        self = first;\n')
    assert not any('__rise = self->index' in text for text in children(source))


def test_offset_spelling_moves_over_other_offsets_only():
    source = '''void f(char *self, char *child) {
    *(s32 *)(child + 4) = 1;
    *(u16 *)(child + 8) = *(u16 *)(self + 8) + 2;
}
'''
    assert any('__rise = *(u16 *)(self + 8) + 2;' in text for text in children(source))
    assert not children(source.replace('*(s32 *)(child + 4) = 1;', '*(s32 *)(child + 8) = 1;'))


def test_volatile_sources_are_left_alone():
    assert not children(SOURCE.replace('u8 state;', 'volatile u8 state;'))
