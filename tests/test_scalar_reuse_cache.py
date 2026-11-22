from collections import Counter

from decomprepair import scalar_storage_reuse


def test_pair_search_reads_type_and_reference_facts_once(monkeypatch):
    source = """
int f(int mode, int x) {
    int first;
    int second;
    short narrow;
    if (mode == 0) {
        first = x;
        use(first);
    } else if (mode == 1) {
        second = x + 1;
        use(second);
    } else {
        narrow = x + 8;
        use(narrow);
    }
    return 0;
}
"""
    types, references = Counter(), Counter()
    original_scalar = scalar_storage_reuse.integer_abi.scalar
    original_refs = scalar_storage_reuse.refs

    def scalar(typ, *args):
        types[typ] += 1
        return original_scalar(typ, *args)

    def refs(part, declaration):
        references[declaration['name']] += 1
        return original_refs(part, declaration)

    monkeypatch.setattr(scalar_storage_reuse.integer_abi, 'scalar', scalar)
    monkeypatch.setattr(scalar_storage_reuse, 'refs', refs)
    options = scalar_storage_reuse.variants(source, 'f', arch='mips')
    assert len(options) == 4
    assert 'first = (short)(x + 8);' in options[0][1]
    assert 'second = (short)(x + 8);' in options[1][1]
    assert types == {'int': 1, 'short': 1}
    assert references == {'first': 1, 'second': 1, 'narrow': 1}
