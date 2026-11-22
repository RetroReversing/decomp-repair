from decomprepair import repair_preflight


def test_repeated_calls_share_the_shadow_check(monkeypatch):
    calls = '    consume(1);\n' * 30
    source = f'extern void consume(int);\nvoid f(void) {{\n{calls}    consume(1, 2);\n}}'
    clean = repair_preflight.clean
    scanned = []

    def observe(text):
        scanned.append(text)
        return clean(text)

    monkeypatch.setattr(repair_preflight, 'clean', observe)
    assert repair_preflight.invalid_call(source, 'f') == 'consume expects 1 arguments; generated call has 2.'
    assert scanned.count(source) == 1


def test_shadowed_name_stays_with_the_compiler():
    source = '''
extern void consume(int);
void f(void (*consume)(int, int)) {
    consume(1, 2);
    consume(3, 4);
}
'''
    assert repair_preflight.invalid_call(source, 'f') == ''
