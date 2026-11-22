"""m2c's refinement makes a byte-stepped typed pointer `char *`, but not one already stepped in elements."""

from decomprepair import m2cfix

ASM = """glabel func_80001000
jr $ra
nop
endlabel func_80001000
"""


def refine(ctype, step):
    draft = (f"void func_80001000(void *arg0) {{\n    {ctype} *var_s0;\n    s32 sum;\n    var_s0 = arg0;\n"
             f"    sum = *var_s0;\n    var_s0 += {step};\n    sum += *var_s0;\n}}\n")
    return m2cfix.refine_draft(draft, "func_80001000", ASM)


def test_a_byte_step_is_made_char_pointer():
    out = refine("u16", 6)
    assert "char *var_s0;" in out and "*(u16 *)var_s0" in out and "var_s0 += 6;" in out


def test_an_element_step_keeps_the_type():
    out = refine("u16", 3)
    assert "u16 *var_s0;" in out and "var_s0 += 3;" in out and "(u16 *)var_s0" not in out
    assert "s32 *var_s0;" in refine("s32", 2)


def test_bytes_step_by_anything():
    assert "char *var_s0;" in refine("u8", 3)
