"""Table API client tests. All HTTP is intercepted by ``responses``; no network is used."""

from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from cmdb_health.sources.servicenow import ConfigurationError, ServiceNowClient, ServiceNowError, ServiceNowSettings

BASE = "https://example.service-now.com"
FAKE = "placeholder-not-a-real-value"


def basic_settings(**kw):
    env = {"SN_INSTANCE_URL": BASE, "SN_USERNAME": "integration.reader", "SN_PASSWORD": FAKE, "SN_PAGE_SIZE": "2"}
    env.update(kw)
    return ServiceNowSettings.from_env(env)


def oauth_settings():
    return ServiceNowSettings.from_env(
        {"SN_INSTANCE_URL": BASE, "SN_AUTH_MODE": "oauth", "SN_CLIENT_ID": "client-id", "SN_CLIENT_SECRET": FAKE}
    )


def client(settings=None, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return ServiceNowClient(settings or basic_settings(), sleep=sleeps.append, backoff_base=0.01)


def qs(call):
    return {k: v[0] for k, v in parse_qs(urlparse(call.request.url).query).items()}


@pytest.mark.parametrize(
    "env, message",
    [
        ({}, "SN_INSTANCE_URL"),
        ({"SN_INSTANCE_URL": "http://insecure.example"}, "https"),
        ({"SN_INSTANCE_URL": BASE}, "SN_USERNAME"),
        ({"SN_INSTANCE_URL": BASE, "SN_AUTH_MODE": "oauth", "SN_CLIENT_ID": "x"}, "SN_CLIENT_SECRET"),
        ({"SN_INSTANCE_URL": BASE, "SN_AUTH_MODE": "kerberos"}, "unsupported"),
    ],
)
def test_settings_validation(env, message):
    with pytest.raises(ConfigurationError, match=message):
        ServiceNowSettings.from_env(env)


def test_settings_repr_does_not_leak_secrets():
    assert FAKE not in repr(basic_settings())


@responses.activate
def test_pagination_uses_limit_offset_and_stops_on_short_page():
    url = f"{BASE}/api/now/table/cmdb_ci_server"
    responses.get(url, json={"result": [{"sys_id": "1"}, {"sys_id": "2"}]})
    responses.get(url, json={"result": [{"sys_id": "3"}]})
    records = list(client().iter_table("cmdb_ci_server", "install_status!=7", ["sys_id"]))
    assert [r["sys_id"] for r in records] == ["1", "2", "3"]
    first, second = qs(responses.calls[0]), qs(responses.calls[1])
    assert first["sysparm_limit"] == "2" and first["sysparm_offset"] == "0"
    assert second["sysparm_offset"] == "2"
    assert first["sysparm_query"] == "install_status!=7^ORDERBYsys_id"
    assert first["sysparm_fields"] == "sys_id"
    assert responses.calls[0].request.headers["Authorization"].startswith("Basic ")


@responses.activate
def test_max_records_caps_results():
    url = f"{BASE}/api/now/table/cmdb_ci_server"
    responses.get(url, json={"result": [{"sys_id": "1"}, {"sys_id": "2"}]})
    assert len(list(client().iter_table("cmdb_ci_server", max_records=1))) == 1
    assert len(responses.calls) == 1


@responses.activate
def test_retries_on_503_with_exponential_backoff():
    url = f"{BASE}/api/now/table/cmdb_ci"
    responses.get(url, status=503)
    responses.get(url, status=502)
    responses.get(url, json={"result": []})
    sleeps: list[float] = []
    assert list(client(sleeps=sleeps).iter_table("cmdb_ci")) == []
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


@responses.activate
def test_honours_retry_after_on_429():
    url = f"{BASE}/api/now/table/cmdb_ci"
    responses.get(url, status=429, headers={"Retry-After": "3"})
    responses.get(url, json={"result": []})
    sleeps: list[float] = []
    list(client(sleeps=sleeps).iter_table("cmdb_ci"))
    assert sleeps == [3.0]


@responses.activate
def test_gives_up_after_max_retries():
    url = f"{BASE}/api/now/table/cmdb_ci"
    for _ in range(5):
        responses.get(url, status=500)
    with pytest.raises(ServiceNowError, match="HTTP 500"):
        list(client(basic_settings(SN_MAX_RETRIES="2")).iter_table("cmdb_ci"))
    assert len(responses.calls) == 3


@responses.activate
def test_connection_errors_are_retried():
    url = f"{BASE}/api/now/table/cmdb_ci"
    responses.get(url, body=requests.ConnectionError("reset"))
    responses.get(url, json={"result": [{"sys_id": "1"}]})
    assert len(list(client().iter_table("cmdb_ci"))) == 1


@responses.activate
def test_403_is_not_retried():
    responses.get(f"{BASE}/api/now/table/cmdb_ci", status=403)
    with pytest.raises(ServiceNowError, match="403"):
        list(client().iter_table("cmdb_ci"))
    assert len(responses.calls) == 1


@responses.activate
def test_oauth_client_credentials_and_refresh_on_401():
    token_url = f"{BASE}/oauth_token.do"
    responses.post(token_url, json={"access_token": "tok-1", "expires_in": 1800})
    responses.post(token_url, json={"access_token": "tok-2", "expires_in": 1800})
    url = f"{BASE}/api/now/table/cmdb_ci"
    responses.get(url, status=401)
    responses.get(url, json={"result": []})
    list(client(oauth_settings()).iter_table("cmdb_ci"))
    assert "grant_type=client_credentials" in responses.calls[0].request.body
    assert responses.calls[1].request.headers["Authorization"] == "Bearer tok-1"
    assert responses.calls[3].request.headers["Authorization"] == "Bearer tok-2"


def test_rejects_suspicious_table_names():
    with pytest.raises(ValueError):
        list(client().iter_table("cmdb_ci/../sys_user"))


@responses.activate
def test_fetch_dataset_filters_relationships_and_marks_partial_scope():
    responses.get(
        f"{BASE}/api/now/table/cmdb_ci_server",
        json={"result": [{"sys_id": "a", "name": "a"}]},
    )
    responses.get(
        f"{BASE}/api/now/table/cmdb_rel_ci",
        json={
            "result": [
                {"sys_id": "r1", "parent": "a", "child": "z", "type.name": "Runs on::Runs"},
                {"sys_id": "r2", "parent": "y", "child": "z", "type.name": "Runs on::Runs"},
            ]
        },
    )
    data = client(basic_settings(SN_PAGE_SIZE="100")).fetch_dataset(["cmdb_ci_server"])
    assert data.cis[0]["sys_class_name"] == "cmdb_ci_server"
    assert [r.sys_id for r in data.relationships] == ["r1"]
    assert data.complete_scope is False
