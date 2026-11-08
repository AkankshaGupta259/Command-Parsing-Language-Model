"""Unit tests for the Task 5 subnet allocation of 10.20.0.0/16."""
import ipaddress

# name -> (cidr, broadcast, usable hosts)
EXPECTED = {
    "app": ("10.20.0.0/22", "10.20.3.255", 1022),
    "public": ("10.20.4.0/24", "10.20.4.255", 254),
    "data": ("10.20.5.0/25", "10.20.5.127", 126),
    "management": ("10.20.5.128/27", "10.20.5.159", 30),
}
NEEDED = {"app": 1000, "public": 250, "data": 100, "management": 20}


def test_subnet_values_are_correct():
    for name, (cidr, bcast, usable) in EXPECTED.items():
        n = ipaddress.ip_network(cidr)
        assert str(n.broadcast_address) == bcast
        assert n.num_addresses - 2 == usable
        assert usable >= NEEDED[name]


def test_prefix_is_the_smallest_that_fits():
    # one bit larger (a smaller prefix number would be wasteful; a larger one too small)
    for name, (cidr, _bcast, _usable) in EXPECTED.items():
        prefix = int(cidr.split("/")[1])
        smaller = 2 ** (32 - (prefix + 1)) - 2   # next block down must NOT fit
        assert smaller < NEEDED[name]


def test_subnets_are_contiguous_and_within_the_block():
    block = ipaddress.ip_network("10.20.0.0/16")
    prev_end = None
    for name in ["app", "public", "data", "management"]:
        n = ipaddress.ip_network(EXPECTED[name][0])
        assert n.subnet_of(block)
        if prev_end is not None:
            assert int(n.network_address) == prev_end + 1
        prev_end = int(n.broadcast_address)
