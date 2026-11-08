# Task 5 — Subnetting and NACL

## Subnet allocation for 10.20.0.0/16

Subnets are allocated from the largest host requirement to the smallest, placed
one after another starting at `10.20.0.0`, each using the smallest prefix that
still fits. The usual rule is **usable hosts = 2^(32 − prefix) − 2** (the network
and broadcast addresses are not usable).

| Subnet | Hosts needed | Network address | Prefix | Usable host range | Broadcast | Usable hosts |
|---|---:|---|---|---|---|---:|
| app | 1,000 | 10.20.0.0 | /22 | 10.20.0.1 – 10.20.3.254 | 10.20.3.255 | 1022 |
| public | 250 | 10.20.4.0 | /24 | 10.20.4.1 – 10.20.4.254 | 10.20.4.255 | 254 |
| data | 100 | 10.20.5.0 | /25 | 10.20.5.1 – 10.20.5.126 | 10.20.5.127 | 126 |
| management | 20 | 10.20.5.128 | /27 | 10.20.5.129 – 10.20.5.158 | 10.20.5.159 | 30 |

### Working

**app — needs 1,000.** 2^(32−22) − 2 = 2^10 − 2 = **1022 ≥ 1000**, and the next
smaller block /23 gives only 2^9 − 2 = 510 < 1000. So **/22** (1024 addresses).
Block: 10.20.0.0 – 10.20.3.255. Next free address: 10.20.4.0.

**public — needs 250.** 2^(32−24) − 2 = 2^8 − 2 = **254 ≥ 250**; /25 gives
126 < 250. So **/24** (256 addresses). Block: 10.20.4.0 – 10.20.4.255. Next free:
10.20.5.0.

**data — needs 100.** 2^(32−25) − 2 = 2^7 − 2 = **126 ≥ 100**; /26 gives
62 < 100. So **/25** (128 addresses). Block: 10.20.5.0 – 10.20.5.127. Next free:
10.20.5.128.

**management — needs 20.** 2^(32−27) − 2 = 2^5 − 2 = **30 ≥ 20**; /28 gives
14 < 20. So **/27** (32 addresses). Block: 10.20.5.128 – 10.20.5.159.

Each subnet starts on a boundary that is a multiple of its own block size, so the
allocation is contiguous and correctly aligned, using 10.20.0.0 – 10.20.5.159 of
the /16.

## NACL for the public subnet

The NACL (`network/nacl.json`) protects the `public` subnet (10.20.4.0/24), where
the load balancer lives. It implements exactly:

- **Inbound** — deny everything from the abusive range 198.51.100.0/24 (rule 100,
  before the web allows); allow TCP 80 and TCP 443 from anywhere (200, 210); allow
  TCP 22 only from the management subnet 10.20.5.128/27 (300); allow replies from
  the app subnet 10.20.0.0/22 on ephemeral ports (400). Everything else is denied.
- **Outbound** — allow TCP 8000 to the app subnet (100); allow replies back to
  clients anywhere on ephemeral ports 1024–65535 (200). Everything else is denied.

Verified with `python tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check`
→ **6 / 6 correct**.

## Why a stateless NACL needs separate rules for reply traffic

A NACL is **stateless**: it does not remember that it allowed an inbound request,
so the response — which travels in the opposite direction — is evaluated from
scratch as a brand-new packet. (A stateful firewall or security group would
auto-permit the return traffic; a NACL will not.) That is why the list needs
explicit reply rules: inbound rule 400 lets the app subnet's responses come back
to the load balancer on its ephemeral ports, and outbound rule 200 lets the load
balancer's responses go back to clients on their ephemeral ports (1024–65535).
Without those rules a connection could open but its replies would be dropped, so
nothing would actually work.

## Why the order of the rules matters for the 198.51.100.0/24 block

Rules are evaluated from the **lowest number upward and the first match wins**.
The abusive range 198.51.100.0/24 must be blocked *even on the web ports*, which
the "allow TCP 80/443 from anywhere" rules (200, 210) would otherwise permit. So
the deny rule must have a **lower number** than those allows — here deny is rule
100. If the deny were numbered higher (e.g. 250), a packet from 198.51.100.9 to
port 443 would match the port-443 allow first and be let in. Sample packet S04
shows the correct behaviour: it is denied by rule 100 before rule 210 is reached.
