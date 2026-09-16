from __future__ import annotations

from ratelimit import client_ip, parse_cidrs

TRUSTED = parse_cidrs("10.0.0.0/8, 192.168.1.1")


def test_no_trusted_proxies_means_peer_wins() -> None:
    assert client_ip(peer="203.0.113.9", forwarded_for="1.2.3.4") == "203.0.113.9"


def test_untrusted_peer_ignores_forwarded_for() -> None:
    assert (
        client_ip(peer="203.0.113.9", forwarded_for="1.2.3.4", trusted_proxies=TRUSTED)
        == "203.0.113.9"
    )


def test_trusted_peer_takes_first_untrusted_hop_from_the_right() -> None:
    xff = "9.9.9.9, 198.51.100.7, 10.1.2.3"
    assert client_ip(peer="10.0.0.1", forwarded_for=xff, trusted_proxies=TRUSTED) == "198.51.100.7"


def test_client_written_hops_left_of_the_proxy_are_never_reached() -> None:
    xff = "1.1.1.1, 198.51.100.7"
    assert (
        client_ip(peer="192.168.1.1", forwarded_for=xff, trusted_proxies=TRUSTED) == "198.51.100.7"
    )


def test_all_hops_trusted_falls_back_to_peer() -> None:
    assert (
        client_ip(peer="10.0.0.1", forwarded_for="10.0.0.2", trusted_proxies=TRUSTED) == "10.0.0.1"
    )


def test_garbage_hop_buckets_as_unknown_instead_of_crashing() -> None:
    assert (
        client_ip(peer="10.0.0.1", forwarded_for="not-an-ip", trusted_proxies=TRUSTED) == "unknown"
    )


def test_missing_peer_is_unknown() -> None:
    assert client_ip(peer=None, forwarded_for="1.2.3.4", trusted_proxies=TRUSTED) == "unknown"


def test_parse_cidrs_accepts_bare_addresses_and_blank_entries() -> None:
    nets = parse_cidrs("10.0.0.0/8,, 2001:db8::1 ,")
    assert [str(n) for n in nets] == ["10.0.0.0/8", "2001:db8::1/128"]
