from decomprepair.mips_entry_loops import applies, candidate

SCAN = '''
glabel scan
/* 00 80002000 80820000 */ lb $v0, ($a0)
/* 04 80002004 0085182B */ sltu $v1, $a0, $a1
/* 08 80002008 3842003F */ xori $v0, $v0, 0x3F
/* 0C 8000200C 0002102B */ sltu $v0, $zero, $v0
/* 10 80002010 00431024 */ and $v0, $v0, $v1
/* 14 80002014 5440FFFA */ bnel $v0, $zero, scan
/* 18 80002018 24840001 */ addiu $a0, $a0, 1
/* 1C 8000201C 03E00008 */ jr $ra
/* 20 80002020 00801021 */ addu $v0, $a0, $zero
'''
POLL = '''
glabel poll
/* 00 80003000 3C028001 */ lui $v0, %hi(flag)
/* 04 80003004 8C424000 */ lw $v0, %lo(flag)($v0)
/* 08 80003008 1440FFFD */ bnez $v0, poll
/* 0C 8000300C 00000000 */ nop
/* 10 80003010 03E00008 */ jr $ra
/* 14 80003014 00000000 */ nop
'''


def test_branch_likely_advances_the_cursor_only_on_the_taken_path():
    assert applies(SCAN)
    text = candidate(SCAN, 'scan')
    assert '(*cursor != 63) & ((u32)cursor < end)' in text
    assert 'cursor++;' in text
    assert candidate(SCAN.replace(', scan\n', ', .L80002000\n'), 'scan') == text


def test_poll_rereads_the_word_through_a_volatile_declaration():
    text = candidate(POLL, 'poll')
    assert 'extern volatile s32 flag;' in text
    assert 'while (flag != 0)' in text
    assert not candidate(POLL, 'poll', 'extern s32 flag;')
    assert not candidate(POLL, 'poll', 'void poll(void);')


def test_entry_loops_require_the_encoded_entry_and_exact_delay_slot():
    assert not candidate(SCAN.replace('5440FFFA', '5440FFFB'), 'scan')
    assert not candidate(SCAN.replace('addiu $a0, $a0, 1', 'nop'), 'scan')
    assert not candidate(SCAN.replace('0x3F', '0x40'), 'scan')
    assert not candidate(POLL.replace('1440FFFD', '1440FFFE'), 'poll')
    assert not candidate(POLL.replace(', poll\n', ', another\n'), 'poll')
