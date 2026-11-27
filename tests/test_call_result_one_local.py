"""A second call of the same function held in a local of its own, written into the first result's local."""
from decomprepair import registry
from decomprepair.call_result_one_local import FAMILY, variants

CODE = '''void f(void *a)
{
    void *scratch;
    register void *rec;

    rec = make();
    if (rec != NULL) {
        scratch = (void *) *(u16 *) a;
        *(s16 *) rec = (s32) scratch + 1;
    }
    scratch = make();
    if (scratch != NULL) {
        *(s32 *) scratch = 2;
    }
    make();
}
'''


def test_the_second_result_goes_into_the_first_local_only_from_its_own_call():
    [(family, child)] = variants(CODE, 'f')
    assert family == FAMILY
    assert child.count('rec = make();') == 2
    assert '*(s32 *) rec = 2;' in child
    assert 'scratch = (void *) *(u16 *) a;' in child


def test_a_first_result_read_after_the_second_call_is_kept():
    assert variants(CODE.replace('    make();\n}', '    release(rec);\n}'), 'f') == []


def test_locals_of_different_types_are_left_alone():
    assert variants(CODE.replace('void *scratch;', 's32 *scratch;'), 'f') == []


def test_the_registry_runs_it():
    assert any(r.module.endswith('call_result_one_local') for r in registry.declared())
