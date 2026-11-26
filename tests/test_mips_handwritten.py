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


def test_a_leaf_that_starts_in_registers_no_compiler_picks_first():
    # lui $t0, 0x3F80; sw $t0, 0($a0) (an N64 SDK's hand-written guMtxIdentF): flagged
    assert '$t0' in mips.asm_reason(words(0x3C083F80, 0xAC880000, JR_RA, NOP), True)
    # IDO starts at $t6, GCC at $v0: compiled
    assert mips.asm_reason(words(0x3C0E3F80, 0xAC8E0000, JR_RA, NOP), True) is None
    assert mips.asm_reason(words(0x3C023F80, 0xAC820000, JR_RA, NOP), True) is None
    # $v0 written too, or a call made: not proof
    assert mips.asm_reason(words(0x3C083F80, 0xAC880000, 0x24020001, JR_RA, NOP), True) is None
    assert mips.asm_reason(words(0x3C083F80, 0x0C000000, NOP, JR_RA, NOP), True) is None


def test_cache_and_atomic_instructions_are_assembly():
    # osInvalICache: cache 0x10, 0($a0) in a loop; no C compiler of the era emits cache, ll or sc
    assert 'cache' in mips.asm_reason(words(0xBC900000, JR_RA, NOP), True)
    assert 'll/sc' in mips.asm_reason(words(0xC0880000, 0xE0880000, JR_RA, NOP), True)
    assert mips.asm_reason(words(0x8C820000, JR_RA, NOP), True) is None  # lw is C


def test_a_short_float_to_64_bit_conversion_is_the_runtimes():
    from decomprepair.mips import asm_reason
    def word(*fields):
        return (0x11 << 26 | fields[0] << 21 | fields[1] << 16 | fields[2] << 11 | fields[3] << 6 | fields[4]).to_bytes(4, 'big')
    jr_ra, nop = (0x03E00008).to_bytes(4, 'big'), bytes(4)
    cvt_d_l = word(21, 0, 12, 0, 0x21)          # cvt.d.l $f0, $f12
    dmfc1 = word(1, 2, 0, 0, 0)                  # dmfc1 $v0, $f0
    assert 'runtime' in asm_reason(cvt_d_l + jr_ra + nop, True)
    assert 'runtime' in asm_reason(dmfc1 + jr_ra + nop, True)
    assert 'runtime' not in (asm_reason((dmfc1 + jr_ra + nop) + bytes(4) + bytes(4 * 60), True) or '')


def test_a_tiny_fpu_control_accessor_is_the_sdks():
    from decomprepair.mips import asm_reason
    cfc1 = (0x11 << 26 | 2 << 21 | 2 << 16 | 31 << 11).to_bytes(4, 'big')   # cfc1 $v0, $31
    ctc1 = (0x11 << 26 | 6 << 21 | 4 << 16 | 31 << 11).to_bytes(4, 'big')   # ctc1 $a0, $31
    jr_ra, nop = (0x03E00008).to_bytes(4, 'big'), bytes(4)
    assert 'control register' in asm_reason(cfc1 + jr_ra + nop, True)
    assert 'control register' in asm_reason(ctc1 + jr_ra + nop, True)
