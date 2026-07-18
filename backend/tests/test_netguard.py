"""SSRF / stdio guards. The decorator ships traces to us; the emit path guards outbound
URLs, so these stay relevant even in the pure-observability build."""
import pytest

from provekit.config import get_settings
from provekit.services.netguard import BlockedURL, guard_stdio, guard_url


def test_guard_url_rejects_a_urls_without_a_host():
    with pytest.raises(BlockedURL):
        guard_url("not-a-url")


def test_guard_url_blocks_link_local_metadata_in_hosted_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "hosted", True)
    with pytest.raises(BlockedURL):
        guard_url("http://169.254.169.254/latest/meta-data")  # cloud metadata endpoint


def test_guard_url_blocks_private_addresses_in_hosted_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "hosted", True)
    with pytest.raises(BlockedURL):
        guard_url("http://10.0.0.5/internal")


def test_guard_stdio_is_blocked_in_hosted_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "hosted", True)
    with pytest.raises(BlockedURL):
        guard_stdio()


def test_guard_stdio_is_allowed_when_not_hosted(monkeypatch):
    monkeypatch.setattr(get_settings(), "hosted", False)
    guard_stdio()  # no raise
