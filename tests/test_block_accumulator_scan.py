from collections import Counter

from decomprepair import block_accumulator_repairs


def test_accumulator_reference_and_flow_scans_are_reused(monkeypatch):
    source = """
int f(int x) {
    int sum;
    {
        sum = x;
        sum += 1;
        consume(sum);
    }
    {
        sum = x;
        sum += 2;
        consume(sum);
    }
    return x;
}
"""
    references = Counter()
    analyses = []
    refs = block_accumulator_repairs.refs
    analyze = block_accumulator_repairs.local_flow.analyze

    def observe_refs(part, decl):
        references[decl['name']] += 1
        return refs(part, decl)

    def observe_flow(code, name):
        analyses.append(name)
        return analyze(code, name)

    monkeypatch.setattr(block_accumulator_repairs, 'refs', observe_refs)
    monkeypatch.setattr(block_accumulator_repairs.local_flow, 'analyze', observe_flow)
    proposals = block_accumulator_repairs.variants(source, 'f')
    assert len(proposals) == 2
    assert all('int __block_sum;' in candidate for _, candidate in proposals)
    assert references == {'sum': 1}
    assert analyses == ['f']
