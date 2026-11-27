"""A field spelled through a record cast moves like an `M2C_FIELD` cell: compared by the member's bytes."""
from decomprepair.statement_slide import variants

# The shape of an app-typed m2c draft: each pointer's fields are members of a struct of its own, reached through a cast.
SOURCE = '''typedef int s32;
typedef signed char s8;
typedef struct { char pad0[0x75]; s8 variant; char pad76[2]; s8 state; char pad79[7]; s32 owner; } Child;
typedef struct { char pad0[0x80]; s32 owner; } Parent;

void f(void *self, void *child) {
    (((Child *) child)->state) = 1;
    (((Child *) child)->variant) = 0;
    (((Child *) child)->owner) = (s32) (((Parent *) self)->owner);
}
'''
COPY = '(((Child *) child)->owner) = (s32) (((Parent *) self)->owner);'


def children(source):
    return [text for _, text in variants(source, 'f')]


def test_the_copy_moves_above_the_constant_stores():
    assert any(t.index(COPY) < t.index('->state) = 1;') for t in children(SOURCE))


def test_two_accesses_of_the_same_bytes_keep_their_order():
    source = SOURCE.replace('->variant) = 0;', '->owner) = 0;')
    for child in children(source):
        assert child.index('->owner) = 0;') < child.index(COPY)


def test_another_struct_reaching_the_same_bytes_of_one_pointer_keeps_their_order():
    source = SOURCE.replace('(((Child *) child)->variant) = 0;', '(((Parent *) child)->owner) = 0;')
    for child in children(source):
        assert child.index('(((Parent *) child)->owner) = 0;') < child.index(COPY)


def test_a_member_of_an_unknown_struct_does_not_move():
    for child in children(SOURCE.replace('typedef struct { char pad0[0x80]; s32 owner; } Parent;\n', '')):
        assert child.index('->variant) = 0;') < child.index(COPY)
