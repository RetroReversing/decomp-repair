from decomprepair import commuted_factor

HEADER = 'typedef float f32; typedef struct { f32 y; f32 speed; f32 out; f32 other; } Row; extern Row rows[];'


def children(body):
    source = 'void func(int id, int k) {\n    ' + body + '\n}\n'
    return [child.split('\n')[1].strip() for _, child in commuted_factor.variants(source, 'func', HEADER)]


def test_a_member_factor_goes_before_the_quotient_in_a_chained_store():
    out = children('rows[id].out = rows[id].other = (40.0f - rows[k].y) / 40.0f * rows[id].speed;')
    assert 'rows[id].out = rows[id].other = rows[id].speed * ((40.0f - rows[k].y) / 40.0f);' in out


def test_a_sum_is_exchanged_without_needless_parentheses():
    assert 'k = k + (id << 2);' in children('k = (id << 2) + k;')


def test_literals_and_calls_stay():
    assert children('k = id * 4;') == []
    assert children('k = next() * id;') == []


def test_two_volatile_reads_keep_their_order():
    source = 'void func(volatile int *p, volatile int a, volatile int b) {\n    *p = a * b;\n}\n'
    assert commuted_factor.variants(source, 'func') == []
