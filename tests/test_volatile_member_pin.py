"""Members of one record made volatile, so a run of its accesses keeps its source order."""
from decomprepair.volatile_member_pin import variants

SOURCE = '''typedef struct Cam {
    s32 x0;
    s32 x4;
    f32 x8;
    f32 xC;
    u8 pad10[0x58];
    s32 x68;
    u8 pad6C[0x30];
    void *x9C;
    u8 padA0[0x58];
    s32 xF8;
} Cam;
extern Cam *D_1;

void f(void)
{
    Cam *c;

    c = D_1;
    c->x9C = g;
    *(s32 *)((u8 *)c + 0x68) = -1;
    c->x4 = 0;
    c->x8 = 293.0f;
    c->xF8 |= 0x40;
}
'''


def _all(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == 'volatile_member_pin']


def test_the_first_two_stores_and_the_read_are_one_child_and_the_raw_store_is_the_member():
    first = _all()[0]
    assert '    volatile s32 x68;\n' in first
    assert '    void *volatile x9C;\n' in first
    assert '    volatile s32 xF8;\n' in first
    assert 'c->x68 = -1;' in first and '(u8 *)c + 0x68' not in first
    assert first.count('volatile') == 3


def test_a_run_with_no_read_is_left_alone():
    assert _all(SOURCE.replace('c->xF8 |= 0x40;', 'c->xF8 = 0x40;')) == []


def test_members_already_volatile_are_not_marked_twice():
    marked = SOURCE.replace('    s32 xF8;', '    volatile s32 xF8;')
    assert not any('volatile volatile' in text for text in _all(marked))
