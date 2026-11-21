from decomprepair.measured_kmc_event_record import variants

SOURCE = '''void f(s32 context, s8 x, s8 y) {
    s16 code;
    s8 first;
    s8 second;
    first = x;
    second = y;
    code = 0xC;
    post(context + 0x48, &code, 0);
}'''
TARGET = '''addiu $sp, $sp, -40
addiu $v0, $zero, 12
addiu $a0, $a0, 72
sb $a1, 20($sp)
addiu $a1, $sp, 16
sb $a2, 21($sp)
move $a2, $zero
sw $ra, 32($sp)
jal post
sh $v0, 16($sp)
lw $ra, 32($sp)
jr $ra
addiu $sp, $sp, 40'''.splitlines()
ROWS = [(' ', x, x) for x in TARGET]
ROWS[3] = ('<', TARGET[3], '')
ROWS[5] = ('<', TARGET[5], '')


def test_recover_stack_record_fields():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_stack_event_record'
    assert 's16 code; s16 pad; s8 first; s8 second; s8 tail[4]' in fixed
    assert '__repair_event.first = x;' in fixed
    assert '__repair_event.second = y;' in fixed
    assert 'post(context + 0x48, &__repair_event.code, 0);' in fixed


def test_requires_matching_target_and_source():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('0xC;', '0xD;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('0x48', '0x40'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('post(', 'other('), 'f', '', ROWS)
    assert not variants(SOURCE.replace('s8 first;', 'volatile s8 first;'), 'f', '', ROWS)
