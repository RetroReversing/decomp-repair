from decomprepair import deref_compound_store as repair
from decomprepair import registry

SOURCE = '''
void advance(void) {
    *((int *) (((char *) gChan) + 0x18)) = (s32) (*((int *) (((char *) gChan) + 0x18)) + 0x10);
    gChan->count = gChan->count - step;
    total = total + 1;
    p->pos = p->pos + a * b;
    q[i++] = q[i++] + 1;
    r->v = next(r) + r->v;
}
'''


def test_direct_updates_become_compound_stores():
    texts = [text for _, text in repair.variants(SOURCE, 'advance')]
    assert '*((int *) (((char *) gChan) + 0x18)) += 0x10;' in texts[0]
    assert 'gChan->count -= step;' in texts[0]
    # a plain global, a lower-precedence operand, a side effect and a call stay as they are
    for kept in ('total = total + 1;', 'p->pos = p->pos + a * b;', 'q[i++] = q[i++] + 1;', 'r->v = next(r) + r->v;'):
        assert kept in texts[0]
    assert len(texts) == 3


def test_it_declares_itself():
    entry = registry.get('deref_compound_store')
    assert entry and not registry.problems(entry)
