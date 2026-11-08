"""Unit tests for the public-subnet NACL (network/nacl.json)."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import nacl_sim  # noqa: E402

RULES = nacl_sim.load_rules(str(ROOT / "network" / "nacl.json"))


def decide(direction, protocol, port, address):
    pkt = {"direction": direction, "protocol": protocol, "port": port, "address": address}
    return nacl_sim.decide(RULES, pkt)[0]


def test_web_ports_allowed_from_anywhere():
    assert decide("inbound", "tcp", 443, "203.0.113.7") == "allow"
    assert decide("inbound", "tcp", 80, "203.0.113.7") == "allow"


def test_abusive_range_blocked_even_on_web_ports():
    assert decide("inbound", "tcp", 443, "198.51.100.9") == "deny"
    assert decide("inbound", "tcp", 80, "198.51.100.1") == "deny"


def test_ssh_only_from_management_subnet():
    assert decide("inbound", "tcp", 22, "10.20.5.130") == "allow"   # management 10.20.5.128/27
    assert decide("inbound", "tcp", 22, "203.0.113.7") == "deny"


def test_outbound_to_app_and_client_replies():
    assert decide("outbound", "tcp", 8000, "10.20.1.5") == "allow"     # to app subnet
    assert decide("outbound", "tcp", 54000, "203.0.113.7") == "allow"  # reply to a client
    assert decide("outbound", "tcp", 22, "203.0.113.7") == "deny"      # not permitted outbound
