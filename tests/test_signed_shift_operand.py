"""signed_shift_operand: `(a - b + 8) >> 3` on an unsigned sum written with the signed cast."""
from decomprepair import registry
from decomprepair import signed_shift_operand as s

DRAFT = '''void put(s32 w, s32 x);
void f(u32 arg0, s32 arg1)
{
    u32 var_t2;
    s32 temp_t3;

    var_t2 = arg0 + 4;
    temp_t3 = arg1;
    put(1, ((var_t2 - temp_t3) + 8) >> 3);
    put(2, ((var_t2 - temp_t3) + 8) >> 3);
    put(3, arg1 >> 2);
}
'''
SRA = 'sra $v0, $v0, 3\n'


def test_the_two_commands_that_share_an_unsigned_operand_get_the_signed_shift_as_one_edit():
    out = s.variants(DRAFT, 'f', asm=SRA)
    assert [family for family, _ in out] == ['signed_shift_operand']
    [(_, child)] = out
    assert child.count('(s32) ((var_t2 - temp_t3) + 8) >> 3') == 2
    assert '(s32) arg1' not in child  # a signed operand has nothing to change


def test_a_target_without_an_arithmetic_shift_proposes_nothing():
    assert s.variants(DRAFT, 'f', asm='srl $v0, $v0, 3\n') == []


def test_an_operand_already_cast_is_left_alone():
    source = DRAFT.replace('((var_t2 - temp_t3) + 8) >> 3', '(s32) ((var_t2 - temp_t3) + 8) >> 3')
    assert s.variants(source, 'f', asm=SRA) == []


def test_distinct_operands_give_one_child_each_and_one_with_all():
    source = DRAFT.replace('put(2, ((var_t2 - temp_t3) + 8) >> 3);', 'put(2, (var_t2 + 1) >> 3);')
    out = s.variants(source, 'f', asm=SRA)
    assert len(out) == 3
    assert out[0][1].count('(s32) (') == 2


def test_the_module_declares_itself_to_the_registry():
    assert any(r.module == 'signed_shift_operand' for r in registry.declared())
