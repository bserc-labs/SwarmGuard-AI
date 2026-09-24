"""Which bucket a telemetry packet counts against.

Keyed on the client address, one ground station's uplink is one bucket and the
fleet behind it divides the ingest limit: the load test measured twenty drones
sharing 50 packets/second, 2.5 Hz each, with one noisy airframe able to spend
the whole allowance. Per-device credentials are a stable identity that arrives
with the packet, so each drone gets its own.
"""

from types import SimpleNamespace

from utils.limiter import DEVICE_KEY_PREFIX, device_or_address


def _request(key: str | None, address: str = "203.0.113.7"):
    headers = {"x-drone-api-key": key} if key is not None else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=address))


class TestTheLimiterKey:
    def test_two_drones_behind_one_address_get_their_own_buckets(self):
        one = device_or_address(_request(f"{DEVICE_KEY_PREFIX}aaaaaaaaaaaa"))
        two = device_or_address(_request(f"{DEVICE_KEY_PREFIX}bbbbbbbbbbbb"))
        assert one != two

    def test_one_drone_keeps_its_bucket_across_uplinks(self):
        # A fleet that fails over to another ground station keeps its limits.
        key = f"{DEVICE_KEY_PREFIX}cccccccccccc"
        assert device_or_address(_request(key, "198.51.100.4")) == device_or_address(
            _request(key, "203.0.113.9")
        )

    def test_the_credential_never_appears_in_the_key(self):
        # Keys reach Redis and error messages; the credential must not.
        key = f"{DEVICE_KEY_PREFIX}secret-value-here"
        assert "secret-value-here" not in device_or_address(_request(key))

    def test_the_shared_fleet_key_still_counts_per_address(self):
        # It identifies no one, so per-device buckets would put the whole fleet
        # in one. Another reason to finish migrating off it.
        shared = "legacy-shared-fleet-key"
        assert device_or_address(_request(shared, "198.51.100.4")) == "198.51.100.4"
        assert device_or_address(_request(shared, "203.0.113.9")) == "203.0.113.9"

    def test_a_packet_with_no_key_counts_per_address(self):
        assert device_or_address(_request(None, "192.0.2.1")) == "192.0.2.1"


class TestTheIngestRouteUsesIt:
    def test_the_limit_on_ingest_is_keyed_per_device(self):
        # The function above is only worth anything if the route is using it.
        import routers.telemetry  # noqa: F401 - registers the route's limit
        from utils.limiter import limiter

        keys = [
            limit.key_func
            for name, limits in limiter._route_limits.items()
            if name.endswith("ingest_telemetry")
            for limit in limits
        ]
        assert keys, "no rate limit is registered on the ingest route"
        assert all(key is device_or_address for key in keys)
