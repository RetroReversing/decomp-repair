"""A loaded value stored after a run of constant stores, moved up into the run."""
import re

from decomprepair import registry
from decomprepair.late_load_store_hoist import FAMILY, variants

CODE = '''void f(Rec *e, Rec *c)
{
    c->f80 = 0x3F2;
    c->type = 1;
    c->a75 = 0;
    c->b = 0x40;
    c->g = 0x40;
    c->r = 0x40;
    c->f84 = 1;
    c->serial = e->serial + 0x21;
    done();
}
'''

STAGED = '''void f(void *a, void *c)
{
    s32 sum;
    void *t;
    (*(s32 *)((char *)(c) + 0x80)) = 0x3F2;
    (*(s8 *)((char *)(c) + 0x78)) = 1;
    t = (void *) (*(u16 *)((char *)(a) + 0x6A)); sum = (u32) t + 0x21;
    (*(s16 *)((char *)(c) + 0x6A)) = (s16) sum;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_loaded_store_is_offered_at_the_head_of_the_constant_run():
    children = variants(CODE, 'f')
    assert [family for family, _ in children] == [FAMILY] * 7
    head = squash(children[0][1])
    assert head.index('c->serial = e->serial + 0x21;') < head.index('c->f80 = 0x3F2;')
    assert head.count('c->serial') == 1


def test_the_staged_locals_move_with_their_store():
    child = squash(variants(STAGED, 'f')[0][1])
    assert child.index('sum = (u32) t + 0x21;') < child.index('(c) + 0x80)) = 0x3F2;')
    assert child.index('(s16) sum;') < child.index('(c) + 0x80)) = 0x3F2;')


def test_a_run_that_writes_what_the_group_reads_stops_the_move():
    children = variants(CODE.replace('c->g = 0x40;', 'e->serial = 0;'), 'f')
    assert len(children) == 2  # only the places below the store of the cell the sum reads
    assert all(c.index('e->serial = 0;') < c.index('c->serial = e->serial') for _, c in children)


def test_a_call_or_a_constant_store_is_not_a_group():
    assert variants(CODE.replace('e->serial + 0x21', 'next() + 0x21'), 'f') == []
    assert variants(CODE.replace('e->serial + 0x21', '0x21'), 'f') == []


def test_the_registry_runs_it():
    assert any(r.module.endswith('late_load_store_hoist') for r in registry.declared())
