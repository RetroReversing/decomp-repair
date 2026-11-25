"""signed_switch: a switch on an unsigned state word written on its signed form."""
from decomprepair import registry
from decomprepair import signed_switch as ss

SOURCE = '''typedef struct Obj { u32 state; s32 timer; } Obj;
void act(Obj *);

void f(Obj *obj) {
    switch (obj->state) {
    case 0:
        obj->state = 1;
        break;
    case 1:
        act(obj);
        obj->state = 2;
        break;
    case 2:
        obj->state = 3;
        break;
    case 3:
        obj->timer -= 0x18;
        break;
    }
}
'''


def test_the_state_switch_is_offered_signed():
    out = ss.variants(SOURCE, 'f')
    assert out == [('signed_switch', SOURCE.replace('switch (obj->state)', 'switch ((s32) obj->state)'))]


def test_a_signed_cast_a_negative_or_named_label_and_a_target_without_slti_get_nothing():
    assert ss.variants(SOURCE.replace('switch (obj->state)', 'switch ((s32) obj->state)'), 'f') == []
    assert ss.variants(SOURCE.replace('case 3:', 'case 0x80000000:'), 'f') == []
    assert ss.variants(SOURCE.replace('case 3:', 'case STATE_END:'), 'f') == []
    assert ss.variants(SOURCE, 'f', 'beq $v1, $v0, .L1\nsltiu $v0, $v1, 4') == []
    assert ss.variants(SOURCE, 'f', 'beq $v1, $a0, .L1\nslti $v0, $v1, 2')


def test_it_is_declared():
    assert registry.get('signed_switch') is not None
