"""Instruction patterns that MIPS compilers never produce for C, read as proof of hand-written assembly.

Three cases, each one a fact about how compiled code is built, not a guess from style:

- Trapping integer arithmetic (`addi`, `add`, `sub` and their doubleword forms). C's integer `+` and `-` don't trap,
  and GCC, IDO and SN emit only `addiu`/`addu`/`subu` (`daddu`, ...). An N64 SDK's `guMtxIdent` was hand-written
  with `addi $t0, $zero, 1`.
- A register cleared by combining it with itself (`xor $a2, $a2, $a2`, `subu $x, $x, $x`). Compilers load zero with
  `move`/`addu ..., $zero` or use `$zero` directly. An N64 library's double-from-words helper began this way.
- A callee-saved register (`$s0`-`$s8`) written in the entry block before it is saved on the stack. C's calling
  convention keeps those registers for the caller, so compiled code saves one before its first write. An N64
  library routine kept its return address in `$s2` (`addu $s2, $ra, $zero`) without saving `$s2`.
"""
from .mips import SPECIAL, _mips_branch, _mips_uses, fields

TRAPPING_IMMEDIATE = {0x08: "addi", 0x18: "daddi"}
TRAPPING_SPECIAL = {0x20: "add", 0x22: "sub", 0x2C: "dadd", 0x2E: "dsub"}
SELF_CLEAR = {0x26: "xor", 0x23: "subu", 0x2F: "dsubu", 0x22: "sub"}
SAVED = set(range(16, 24)) | {30}  # s0-s7, s8/fp
SP = 29


def _name(r):
    return f"s{r - 16}" if 16 <= r <= 23 else "s8" if r == 30 else f"r{r}"


def reason(words: list[int]) -> str | None:
    """Why these instruction words (a function from its entry) can't be compiled C, or None."""
    for w in words:
        op, rs, rt, rd, funct = fields(w)
        if op in TRAPPING_IMMEDIATE:
            return (f"uses {TRAPPING_IMMEDIATE[op]} (integer arithmetic that traps on overflow): C's + and - don't "
                    "trap, and its compilers emit addiu/addu instead")
        if op == SPECIAL and funct in TRAPPING_SPECIAL and rd != 0:
            return (f"uses {TRAPPING_SPECIAL[funct]} (integer arithmetic that traps on overflow): C's + and - "
                    "don't trap, and its compilers emit addu/subu instead")
        if op == SPECIAL and funct in SELF_CLEAR and rs == rt == rd and rd != 0:
            return (f"clears a register with {SELF_CLEAR[funct]} of itself: compilers load zero from $zero, so this "
                    "is hand-written assembly")
    saved = set()
    for i, w in enumerate(words):
        op, rs, rt, rd, funct = fields(w)
        uses = _mips_uses(w)
        if uses is None:
            return None
        if op in (0x2B, 0x3F, 0x1F) and rs == SP and rt in SAVED:  # sw / sd / sq (the PS2's EE) sX, off($sp)
            saved.add(rt)
        written = uses[1] & SAVED
        # (a move between saved registers that only renames, e.g. `addu s0, s0, zero`, can't happen in C either)
        if written - saved:
            return (f"writes {_name(min(written - saved))} before saving it: compiled code keeps callee-saved "
                    "registers for its caller and saves one before its first write")
        if _mips_branch(w):
            break  # only the entry block, its delay slot not included: later blocks may be reached otherwise
    return None

