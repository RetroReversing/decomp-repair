"""The scheduling boundary: proposals only, nothing is compiled here."""
import re

from decomprepair.scheduling_scope import variants

# The shape of a display-list function (GCC 2.7.2, KMC) that stayed at 60 until its last statements were split in two.
HEADER = '''extern s32 D_8010A4D8;
extern void *D_80109CB8;
extern void *sDisplayListCursor;
extern void *sRenderState;
s32 func_80034928();
'''
BEFORE = HEADER + '''void f(s32 arg0) {
    void *temp_a2;
    func_80034928(arg0, 2);
    ((S *)D_80109CB8)->value = 0xDF000000;
    ((S *)D_80109CB8 + 1)->value = 0;
    ((S *)sDisplayListCursor)->value = 0xDE000000;
    M2C_FIELD(sDisplayListCursor, s32 *, 4) = (s32) M2C_FIELD(sRenderState, s32 *, 0x1A60);
    D_80109CB8 += 8;
    temp_a2 = sDisplayListCursor + 8;
    sDisplayListCursor = temp_a2;
    func_80034928(arg0, D_8010A4D8, temp_a2);
}
'''
# What the judge called 0 (the matched source's tail, with the repair's own local name).
MATCHED_TAIL = '''    repair_scope_1 = D_8010A4D8;
    D_80109CB8 += 8;
    do {
        temp_a2 = sDisplayListCursor + 8;
        sDisplayListCursor = temp_a2;
        func_80034928(arg0, repair_scope_1, temp_a2);
    } while (0);
}
'''


def _all(text, name='f'):
    return [src for fam, src in variants(text, name) if fam == 'scheduling_scope']


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_matched_shape_is_one_of_the_proposals():
    assert any(MATCHED_TAIL in src for src in _all(BEFORE))
    assert all('repair_scope_1;' in src for src in _all(BEFORE) if 'repair_scope_1 =' in src)


def test_the_boundary_alone_wraps_the_second_half_through_the_last_call():
    srcs = _all(BEFORE)
    plain = [s for s in srcs if 'repair_scope' not in s]
    assert plain
    assert any(_squash('do { temp_a2 = sDisplayListCursor + 8; sDisplayListCursor = temp_a2; '
                       'func_80034928(arg0, D_8010A4D8, temp_a2); } while (0);') in _squash(s) for s in plain)


def test_every_proposal_keeps_the_same_statements_and_the_scalar_local_is_declared():
    for src in _all(BEFORE):
        body = src.replace('do {', '').replace('} while (0);', '')
        assert body.count('D_80109CB8 += 8;') == 1
        if 'repair_scope_1 =' in src:
            assert re.search(r'\n    s32 repair_scope_1;', src)
        assert src.count('do {') == src.count('} while (0);') == 1


def test_the_first_call_and_the_run_before_it_are_never_wrapped():
    for src in _all(BEFORE):
        assert src.index('func_80034928(arg0, 2);') < src.index('do {')


def test_nothing_is_proposed_for_other_arch_short_bodies_or_branches_in_the_run():
    assert variants(BEFORE, 'f', 'x86') == []
    assert not _all('void f(void) {\n    a = 1;\n    g();\n}\n')
    branchy = BEFORE.replace('    D_80109CB8 += 8;\n', '    if (arg0) { D_80109CB8 += 8; }\n')
    for src in _all(branchy):
        assert src.index('if (arg0)') < src.index('do {')


def test_proposals_are_capped_and_distinct():
    many = HEADER + 'void f(s32 arg0) {\n' + ''.join(f'    v{i} = {i};\n' for i in range(40)) + \
        '    func_80034928(arg0, D_8010A4D8);\n}\n'
    srcs = _all(many)
    assert len(srcs) == len(set(srcs)) <= 64
