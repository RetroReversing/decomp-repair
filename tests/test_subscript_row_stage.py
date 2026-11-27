from decomprepair import subscript_row_stage

SOURCE = '''void func(Sel *sel)
{
    car->a = send(sel->id, T[sel->id * 0x110 + sel->b]);
    car->b = U[sel->id * 0x110 + sel->a];
}
'''


def test_every_site_shares_one_local():
    children = [source for _, source in subscript_row_stage.variants(SOURCE, 'func')]
    assert len(children) == 3
    together = children[-1]
    assert 'T[(row_term = sel->id * 0x110) + sel->b]' in together
    assert 'U[(row_term = sel->id * 0x110) + sel->a]' in together
    assert together.count('s32 row_term;') == 1


def test_one_assignment_per_statement():
    source = 'void func(s32 i, s32 j) { out = T[i * 8 + j] + U[8 * i + j]; v = T[i * 8 + j]; }\n'
    together = subscript_row_stage.variants(source, 'func')[-1][1]
    assert together.count('row_term = ') == 2
    assert 'T[(row_term = i * 8) + j] + U[8 * i + j]' in together


def test_calls_and_other_shapes_are_left_alone():
    assert not subscript_row_stage.variants('void func(s32 i) { v = T[next() * 8 + i]; }\n', 'func')
    assert not subscript_row_stage.variants('void func(s32 i) { v = T[i + 8]; }\n', 'func')
    assert not subscript_row_stage.variants('void func(s32 i) { v = T[i++ * 8 + i]; }\n', 'func')
