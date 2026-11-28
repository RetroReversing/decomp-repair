"""A computation below an early exit, written above it, only when the exit path never reads it."""
from decomprepair import exit_guard_assign_hoist as m
from decomprepair import registry

SOURCE = '''int unpack(unsigned char *in)
{
    int len;
    int byte;
    int total;
    total = 0;
loop:
    byte = *in;
    if (byte == 0) {
        goto out;
    }
    len = byte + 8;
    total += len;
    in++;
    goto loop;
out:
    return total;
}
'''


def texts(source=SOURCE):
    return [text for _, text in m.variants(source, 'unpack')]


def test_the_assignment_moves_above_the_exit():
    assert any(t.index('len = byte + 8;') < t.index('if (byte == 0)') for t in texts())


def test_a_value_the_exit_path_reads_stays():
    assert not texts(SOURCE.replace('return total;', 'return total + len;'))


def test_a_memory_read_or_a_call_stays():
    assert not texts(SOURCE.replace('len = byte + 8;', 'len = *in + 8;'))
    assert not texts(SOURCE.replace('len = byte + 8;', 'len = next(byte);'))


def test_a_return_that_names_the_value_stays():
    source = SOURCE.replace('goto out;', 'return len;')
    assert not texts(source)
    assert texts(SOURCE.replace('goto out;', 'return 0;'))


def test_it_is_registered():
    repair = registry.get('exit_guard_assign_hoist')
    assert repair and registry.problems(repair) == []
