"""m2c's refinement makes the game's callees unprototyped, but not one that takes a float by value: without its
prototype the caller would pass a promoted double (a KMC gcc 2.7.2 collision sweep gained a cvt.d.s and an mfc1)."""

from decomprepair import m2cfix

ASM = """glabel func_80001000
addiu $sp, $sp, -0x18
sw $ra, 0x10($sp)
jal func_80002000
nop
lw $ra, 0x10($sp)
jr $ra
addiu $sp, $sp, 0x18
endlabel func_80001000
"""


def refine(prototypes):
    draft = prototypes + "void func_80001000(void *arg0, f32 arg1) {\n    func_80002000(arg0, arg1);\n}\n"
    return m2cfix.refine_draft(draft, "func_80001000", ASM)


def test_a_float_parameter_keeps_its_prototype():
    out = refine("s32 func_80002000(void *, f32);\n")
    assert "s32 func_80002000(void *, f32);" in out


def test_named_and_double_parameters_keep_theirs_too():
    assert "s32 func_80002000(void *p, float x);" in refine("s32 func_80002000(void *p, float x);\n")
    assert "s32 func_80002000(void *, f64);" in refine("s32 func_80002000(void *, f64);\n")


def test_pointers_to_floats_and_integers_are_still_unprototyped():
    assert "s32 func_80002000();" in refine("s32 func_80002000(void *, f32 *);\n")
    assert "s32 func_80002000();" in refine("s32 func_80002000(void *, s32);\n")


def test_a_library_guess_with_a_float_keeps_it():
    out = refine("s32 func_80002000(void *, f32);\nf32 sqrtf(f32); /* extern */\n")
    assert "f32 sqrtf(f32); /* extern */" in out
