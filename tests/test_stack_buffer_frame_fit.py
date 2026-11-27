"""stack_buffer_frame_fit: the buffer a call fills is resized to the room the target's frame leaves for locals.

A synthetic 0x40 frame (`$ra` at 0x3C, `$s0` at 0x38, argument area 0x10): 0x28 bytes of room; one `volatile` word
beside the buffer leaves 0x20 for it. Not measured on a matched function: the family is a hypothesis."""
from decomprepair import stack_buffer_frame_fit as s

ASM = '''glabel f
addiu      $sp, $sp, -0x40
sw         $ra, 0x3C($sp)
sw         $s0, 0x38($sp)
addu       $s0, $a0, $zero
addiu      $a1, $sp, 0x10
jal        g
nop
'''
SOURCE = '''void f(void *arg0) {
    char sp10[0x10];
    volatile int sp24;

    g(arg0, sp10, 1);
}
'''


def _texts(source=SOURCE, asm=ASM):
    return [t for fam, t in s.variants(source, 'f', asm) if fam == s.FAMILY]


def test_room_is_read_from_the_prologue():
    assert s.room(ASM) == (0x38, 16)


def test_buffer_fills_the_room_with_and_without_the_scalar():
    texts = _texts()
    assert 'char sp10[0x20];' in texts[0] and 'char sp10[0x28];' in texts[1]


def test_a_buffer_of_that_size_gets_no_child():
    assert [t for t in _texts(SOURCE.replace('0x10]', '0x20]')) if 'sp10[0x28]' not in t] == []


def test_no_saved_registers_no_child():
    assert _texts(asm='addiu $sp, $sp, -0x20\nsw $a0, 0x10($sp)\n') == []


def test_two_arrays_are_ambiguous():
    assert _texts(SOURCE.replace('volatile int sp24;', 'char sp30[8];')) == []
