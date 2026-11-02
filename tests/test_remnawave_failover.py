from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

import src.infrastructure.di.providers.remnawave as provider_module
from src.core.config.remnawave import RemnawaveConfig
from src.infrastructure.di.providers.remnawave import RemnawaveProvider
from src.infrastructure.remnawave_client import RemnawaveFailoverClient
from src.infrastructure.remnawave_v3.client import RemnawaveV3Client

_URLS = ("https://primary.example.com", "https://backup.example.com")


def _config(host="remnawave"):
    return RemnawaveConfig(
        _env_file=None, host=host, token="test-token", webhook_secret="test-webhook"
    )


@pytest.mark.parametrize(
    ("host", "urls"),
    [
        ("remnawave", ("http://remnawave:3000",)),
        ("http://remnawave:3000/", ("http://remnawave:3000",)),
        ("panel.example.com", ("https://panel.example.com",)),
        ("panel.example.com:8443", ("http://panel.example.com:8443",)),
        ("https://panel.example.com/", ("https://panel.example.com",)),
        ("http://panel.example.com", ("http://panel.example.com:3000",)),
        ("http://panel.example.com:80", ("http://panel.example.com",)),
        ("127.0.0.1:3001", ("http://127.0.0.1:3001",)),
        ("http://[::1]:3001", ("http://[::1]:3001",)),
        ("https://panel.example.com/prefix/", ("https://panel.example.com/prefix",)),
        (
            " panel.example.com/ , https://backup.example.com/ , remnawave ",
            ("https://panel.example.com", "https://backup.example.com", "http://remnawave:3000"),
        ),
        ("panel.example.com,https://panel.example.com/", ("https://panel.example.com",)),
    ],
)
def test_host_configuration(host, urls):
    config = _config(host)
    assert tuple(url.get_secret_value() for url in config.urls) == urls
    assert config.url.get_secret_value() == urls[0]
    assert config.is_external == urls[0].startswith("https://")


@pytest.mark.parametrize(
    "host",
    [
        "",
        "panel.example.com,",
        ",panel.example.com",
        "panel.example.com,,backup.example.com",
        "panel.example.com backup.example.com",
        "ftp://panel.example.com",
        "https://",
        "https://user:password@panel.example.com",
        "https://panel.example.com?token=secret",
        "https://panel.example.com#fragment",
        "https://panel.example.com:invalid",
    ],
)
def test_invalid_host_list_is_rejected_at_startup(host):
    with pytest.raises(ValidationError):
        _config(host)


def test_host_list_is_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("REMNAWAVE_HOST", "panel.example.com,backup.example.com")
    config = RemnawaveConfig(_env_file=None, token="test-token", webhook_secret="test-webhook")
    assert tuple(url.get_secret_value() for url in config.urls) == (
        "https://panel.example.com",
        "https://backup.example.com",
    )
    assert "panel.example.com" not in repr(config)


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ConnectTimeout])
async def test_connection_failure_switches_address_and_keeps_working_address(method, failure):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "primary.example.com":
            raise failure("Unavailable", request=request)
        return httpx.Response(200, json={"ok": True})

    async with RemnawaveFailoverClient(
        _URLS,
        transport=httpx.MockTransport(handle),
        headers={"Authorization": "Bearer secret", "X-Api-Key": "proxy-key"},
        cookies={"session": "cookie-value"},
        timeout=httpx.Timeout(connect=15, read=25, write=10, pool=5),
    ) as client:
        response = await client.request(
            method, "users/a%2Fb", params={"filter": "a b"}, json={"x": 1}
        )
        assert response.json() == {"ok": True}
        assert response.request.url.host == "backup.example.com"
        await client.get("system/metadata")

    assert [request.url.host for request in requests] == [
        "primary.example.com",
        "backup.example.com",
        "backup.example.com",
    ]
    for request in requests[:2]:
        assert request.url.raw_path.startswith(b"/api/users/a%2Fb?")
        assert request.url.params["filter"] == "a b"
        assert request.url.raw_path == requests[0].url.raw_path
        assert request.headers["host"] == request.url.host
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.headers["X-Api-Key"] == "proxy-key"
        assert request.headers["Cookie"] == "session=cookie-value"
        assert request.content == requests[0].content
        assert request.extensions["timeout"] == {"connect": 15, "read": 25, "write": 10, "pool": 5}


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout,
        httpx.ReadError,
        httpx.WriteTimeout,
        httpx.WriteError,
        httpx.RemoteProtocolError,
        httpx.ProxyError,
    ],
)
@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
async def test_ambiguous_network_failures_replay_only_reads(failure, method):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "primary.example.com":
            raise failure("Response lost", request=request)
        return httpx.Response(200)

    async with RemnawaveFailoverClient(_URLS, transport=httpx.MockTransport(handle)) as client:
        if method == "GET":
            assert (await client.get("users")).status_code == 200
            assert len(requests) == 2
        else:
            with pytest.raises(failure):
                await client.request(method, "users", json={"username": "new-user"})
            assert len(requests) == 1
        # An independent subsequent request can use the backup even after a lost write response.
        await client.get("system/metadata")
        assert requests[-1].url.host == "backup.example.com"


@pytest.mark.parametrize("status", [502, 503, 504])
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_gateway_errors_replay_only_reads(status, method):
    requests = []
    failed_response = httpx.Response(status)

    def handle(request):
        requests.append(request)
        return failed_response if request.url.host == "primary.example.com" else httpx.Response(200)

    async with RemnawaveFailoverClient(_URLS, transport=httpx.MockTransport(handle)) as client:
        response = await client.request(method, "users")
        assert response.status_code == (200 if method == "GET" else status)
    assert len(requests) == (2 if method == "GET" else 1)
    assert failed_response.is_closed


@pytest.mark.parametrize("status", [200, 400, 401, 403, 404, 409, 422, 429, 500])
async def test_application_responses_are_not_retried(status):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status)

    async with RemnawaveFailoverClient(_URLS, transport=httpx.MockTransport(handle)) as client:
        assert (await client.get("users")).status_code == status
    assert len(requests) == 1


async def test_each_address_is_tried_once_when_all_are_unavailable():
    requests = []

    def handle(request):
        requests.append(request)
        raise httpx.ConnectTimeout("Unavailable", request=request)

    urls = (*_URLS, "http://remnawave:3000")
    async with RemnawaveFailoverClient(urls, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(httpx.ConnectTimeout) as error:
            await client.get("system/metadata")
    assert [str(request.url) for request in requests] == [
        f"{url}/api/system/metadata" for url in urls
    ]
    assert error.value.request.url.host == "remnawave"


async def test_failover_returns_to_recovered_primary_when_backup_fails():
    requests = []
    failed_host = "primary.example.com"

    def handle(request):
        requests.append(request)
        if request.url.host == failed_host:
            raise httpx.ConnectError("Unavailable", request=request)
        return httpx.Response(200)

    async with RemnawaveFailoverClient(_URLS, transport=httpx.MockTransport(handle)) as client:
        await client.get("users")
        failed_host = "backup.example.com"
        await client.get("users")
        await client.get("users")
    assert [request.url.host for request in requests] == [
        "primary.example.com",
        "backup.example.com",
        "backup.example.com",
        "primary.example.com",
        "primary.example.com",
    ]


async def test_failover_preserves_per_address_prefix_port_and_proxy_headers():
    requests = []

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("Unavailable", request=request)
        return httpx.Response(200)

    async with RemnawaveFailoverClient(
        ("https://primary.example.com/panel", "http://remnawave:3000/private"),
        transport=httpx.MockTransport(handle),
    ) as client:
        await client.get("users?offset=10")
    assert str(requests[0].url) == "https://primary.example.com/panel/api/users?offset=10"
    assert "x-forwarded-proto" not in requests[0].headers
    assert str(requests[1].url) == "http://remnawave:3000/private/api/users?offset=10"
    assert requests[1].headers["host"] == "remnawave:3000"
    assert requests[1].headers["x-forwarded-proto"] == "https"
    assert requests[1].headers["x-forwarded-for"] == "127.0.0.1"


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_body_read_timeout_replays_only_reads_and_closes_failed_response(method):
    class BrokenStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'{"response":'
            raise httpx.ReadTimeout("Body lost")

        async def aclose(self):
            self.closed = True

    broken = BrokenStream()
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "primary.example.com":
            return httpx.Response(200, stream=broken)
        return httpx.Response(200, json={"response": {"total": 0}})

    async with RemnawaveFailoverClient(_URLS, transport=httpx.MockTransport(handle)) as client:
        if method == "GET":
            response = await client.get("users")
            assert response.json() == {"response": {"total": 0}}
            assert len(requests) == 2
        else:
            with pytest.raises(httpx.ReadTimeout) as error:
                await client.post("users", json={"username": "test"})
            assert error.value.request.url.host == "primary.example.com"
            assert len(requests) == 1
    assert broken.closed


async def test_internal_to_external_failover_removes_internal_proxy_headers():
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "remnawave":
            raise httpx.ConnectTimeout("Unavailable", request=request)
        return httpx.Response(200)

    async with RemnawaveFailoverClient(
        ("http://remnawave:3000", "https://backup.example.com"),
        transport=httpx.MockTransport(handle),
    ) as client:
        await client.get("users")
    assert requests[0].headers["x-forwarded-proto"] == "https"
    assert "x-forwarded-proto" not in requests[1].headers
    assert "x-forwarded-for" not in requests[1].headers


@pytest.mark.parametrize("urls", [_URLS, _URLS[:1]])
async def test_all_gateway_failures_return_last_response_without_looping(urls):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(503)

    async with RemnawaveFailoverClient(urls, transport=httpx.MockTransport(handle)) as client:
        response = await client.get("users")
        assert response.status_code == 503
        assert len(requests) == len(urls)


async def test_absolute_unrelated_urls_are_not_routed_to_panel():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(503)

    async with RemnawaveFailoverClient(_URLS, transport=httpx.MockTransport(handle)) as client:
        assert (await client.get("https://other.example.com/api/users")).status_code == 503
    assert len(requests) == 1
    assert requests[0].url.host == "other.example.com"


@pytest.mark.parametrize("api_version", [2, 3])
async def test_provider_routes_both_api_versions_and_closes_client(monkeypatch, api_version):
    requests = []
    clients = []

    def handle(request):
        requests.append(request)
        if request.url.host == "primary.example.com":
            raise httpx.ConnectError("Unavailable", request=request)
        return httpx.Response(
            200,
            json={
                "response": {
                    "version": f"{api_version}.8.1",
                    "build": {"time": "2026-11-02", "number": "1"},
                    "git": {
                        "backend": {"commitSha": "test", "branch": "main", "commitUrl": ""},
                        "frontend": {"commitSha": "test", "commitUrl": ""},
                    },
                }
            },
        )

    def build_client(**kwargs):
        client = RemnawaveFailoverClient(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(provider_module, "RemnawaveFailoverClient", build_client)
    config = _config(",".join(_URLS))
    config.api_version = api_version
    provider = RemnawaveProvider()
    session = provider.get_remnawave(SimpleNamespace(remnawave=config))
    async for sdk in session:
        panel = provider.get_panel_client(sdk, SimpleNamespace(remnawave=config))
        if api_version == 2:
            assert (await sdk.system.get_metadata()).version == "2.8.1"
        else:
            assert str(await panel.v3.try_connection()) == "3.8.1"
        assert isinstance(panel.v3, RemnawaveV3Client)
    assert clients[0].is_closed
    assert [request.url.host for request in requests] == [
        "primary.example.com",
        "backup.example.com",
    ]
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in requests)
