"""Instruction patterns compiled C never has, as proof of hand-written MIPS assembly."""
from decomprepair import mips
from decomprepair.mips_handwritten import reason


def words(*ws):
    return b''.join(w.to_bytes(4, 'big') for w in ws)


JR_RA, NOP = 0x03E00008, 0


def test_trapping_arithmetic():
    # addi $t0, $zero, 1 (an N64 SDK's hand-written guMtxIdent)
    assert 'addi' in mips.asm_reason(words(0x20080001, 0xAC880000, JR_RA, NOP), True)
    # add $v0, $a0, $a1
    assert 'add ' in mips.asm_reason(words(0x00851020, JR_RA, NOP), True)
    # addu / addiu are what compilers emit
    assert mips.asm_reason(words(0x00851021, 0x24840001, JR_RA, NOP), True) is None


def test_a_register_cleared_with_itself():
    # xor $a2, $a2, $a2
    assert 'xor' in mips.asm_reason(words(0x00C63026, JR_RA, NOP), True)
    # xor $a2, $a2, $a3 is ordinary
    assert mips.asm_reason(words(0x00C73026, JR_RA, NOP), True) is None


def test_a_saved_register_written_before_it_is_saved():
    # addu $s2, $ra, $zero at the entry, never saved
    assert 's2 before saving' in mips.asm_reason(words(0x03E09021, JR_RA, NOP), True)
    # addiu sp,-0x18; sw s0,0x10(sp); move s0,a0; ...: compiled code saves first
    ok = words(0x27BDFFE8, 0xAFB00010, 0x00808021, 0x8FB00010, JR_RA, 0x27BD0018)
    assert mips.asm_reason(ok, True) is None
    # the PS2's EE saves with sq
    ee = words(0x27BDFFE0, 0x7FB00010, 0x00808021, 0x7BB00010, JR_RA, 0x27BD0020)
    assert reason([int.from_bytes(ee[i:i + 4], 'big') for i in range(0, len(ee), 4)]) is None


def test_only_the_entry_block_is_read_for_saved_registers():
    # bnez a0 ...; then s0 written: another block may come after a save on another path
    assert reason([0x14800002, NOP, 0x00808021, JR_RA, NOP]) is None
