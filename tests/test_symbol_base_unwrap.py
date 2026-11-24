"""symbol_base_unwrap: a pointer set once to `&G` and only dereferenced, written as `G` (a KMC GCC 2.7.2 collision
routine: 15070 -> 14705). The source below is made up; it only has that shape."""
from decomprepair import registry
from decomprepair import symbol_base_unwrap as unwrap

SOURCE = """extern void *gActor;
void f(void *a, s32 n) {
    void **__base_gActor;
    __base_gActor = &gActor;
    *__base_gActor = NULL;
    if (n) {
        *__base_gActor = a;
    }
    if ((*__base_gActor) != NULL) {
        *(s32 *)((char *)(*__base_gActor) + 4) = n;
    }
}
"""


def test_every_dereference_is_the_global_and_the_pointer_goes():
    [(family, text)] = unwrap.variants(SOURCE, 'f')
    assert family == 'symbol_base_unwrap'
    assert '__base_gActor' not in text
    assert 'gActor = NULL;' in text and 'gActor = a;' in text
    assert 'if (gActor != NULL)' in text and '((char *)(gActor) + 4)' in text


def test_a_pointer_used_other_than_through_a_dereference_stays():
    assert not unwrap.variants(SOURCE.replace('*__base_gActor = a;', '__base_gActor[0] = a;'), 'f')
    assert not unwrap.variants(SOURCE.replace('*__base_gActor = a;', 'g(__base_gActor);'), 'f')
    assert not unwrap.variants(SOURCE.replace('*__base_gActor = a;', '__base_gActor = &other;'), 'f')


def test_it_is_declared_in_the_registry():
    assert 'symbol_base_unwrap' in {r.module.rsplit('.', 1)[-1] for r in registry.declared()}
