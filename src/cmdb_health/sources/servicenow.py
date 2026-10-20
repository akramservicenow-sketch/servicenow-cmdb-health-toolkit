"""Read-only ServiceNow Table API client for CMDB tables.

Credentials are read from environment variables only and are never logged.

Environment variables
---------------------
SN_INSTANCE_URL     https://<instance>.service-now.com (required)
SN_AUTH_MODE        ``basic`` (default) or ``oauth``
SN_USERNAME         basic auth user, or resource owner for the OAuth password grant
SN_PASSWORD         basic auth password, or resource owner password
SN_CLIENT_ID        OAuth client id
SN_CLIENT_SECRET    OAuth client secret
SN_OAUTH_GRANT      ``client_credentials`` (default) or ``password``
SN_TIMEOUT          request timeout in seconds (default 30)
SN_PAGE_SIZE        sysparm_limit per page (default 500)
SN_MAX_RETRIES      retries for 429/5xx/connection errors (default 4)
SN_VERIFY_TLS       ``true`` (default) / ``false`` -- only disable for lab instances
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import requests

from cmdb_health.models import Dataset
from cmdb_health.sources.local import normalise_ci, to_relationship

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

DEFAULT_CI_FIELDS = [
    "sys_id",
    "name",
    "sys_class_name",
    "serial_number",
    "mac_address",
    "ip_address",
    "fqdn",
    "object_id",
    "os",
    "version",
    "manufacturer",
    "model_id",
    "location",
    "operational_status",
    "install_status",
    "support_group",
    "owned_by",
    "managed_by",
    "service_classification",
    "last_discovered",
    "discovery_source",
    "sys_updated_on",
]
REL_FIELDS = ["sys_id", "parent", "child", "type.name"]


class ServiceNowError(RuntimeError):
    pass


class ConfigurationError(ServiceNowError):
    pass


@dataclass
class ServiceNowSettings:
    instance_url: str
    auth_mode: str = "basic"
    username: str | None = None
    password: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    oauth_grant: str = "client_credentials"
    timeout: float = 30.0
    page_size: int = 500
    max_retries: int = 4
    verify_tls: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ServiceNowSettings:
        env = os.environ if env is None else env
        url = (env.get("SN_INSTANCE_URL") or "").rstrip("/")
        if not url:
            raise ConfigurationError("SN_INSTANCE_URL is not set")
        if not url.startswith("https://"):
            raise ConfigurationError("SN_INSTANCE_URL must use https://")
        settings = cls(
            instance_url=url,
            auth_mode=(env.get("SN_AUTH_MODE") or "basic").lower(),
            username=env.get("SN_USERNAME") or None,
            password=env.get("SN_PASSWORD") or None,
            client_id=env.get("SN_CLIENT_ID") or None,
            client_secret=env.get("SN_CLIENT_SECRET") or None,
            oauth_grant=(env.get("SN_OAUTH_GRANT") or "client_credentials").lower(),
            timeout=float(env.get("SN_TIMEOUT") or 30),
            page_size=int(env.get("SN_PAGE_SIZE") or 500),
            max_retries=int(env.get("SN_MAX_RETRIES") or 4),
            verify_tls=(env.get("SN_VERIFY_TLS") or "true").lower() not in {"false", "0", "no"},
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.auth_mode == "basic":
            if not (self.username and self.password):
                raise ConfigurationError("basic auth requires SN_USERNAME and SN_PASSWORD")
        elif self.auth_mode == "oauth":
            if not (self.client_id and self.client_secret):
                raise ConfigurationError("oauth requires SN_CLIENT_ID and SN_CLIENT_SECRET")
            if self.oauth_grant == "password" and not (self.username and self.password):
                raise ConfigurationError("oauth password grant requires SN_USERNAME and SN_PASSWORD")
            if self.oauth_grant not in {"client_credentials", "password"}:
                raise ConfigurationError(f"unsupported SN_OAUTH_GRANT '{self.oauth_grant}'")
        else:
            raise ConfigurationError(f"unsupported SN_AUTH_MODE '{self.auth_mode}'")
        if not 1 <= self.page_size <= 10000:
            raise ConfigurationError("SN_PAGE_SIZE must be between 1 and 10000")

    def __repr__(self) -> str:  # never leak secrets in logs / tracebacks
        return f"ServiceNowSettings(instance_url={self.instance_url!r}, auth_mode={self.auth_mode!r})"


class ServiceNowClient:
    """Minimal, read-only Table API client with pagination, retries and OAuth."""

    def __init__(
        self,
        settings: ServiceNowSettings,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        backoff_base: float = 0.5,
        backoff_cap: float = 30.0,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "cmdb-health-toolkit"})
        self._sleep = sleep
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._token: str | None = None
        self._token_expiry: float = 0.0
        if settings.auth_mode == "basic":
            self.session.auth = (settings.username or "", settings.password or "")

    # ---- auth -------------------------------------------------------------------

    def _ensure_token(self) -> None:
        if self.settings.auth_mode != "oauth":
            return
        if self._token and time.monotonic() < self._token_expiry - 60:
            return
        data = {
            "grant_type": self.settings.oauth_grant,
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
        }
        if self.settings.oauth_grant == "password":
            data.update({"username": self.settings.username, "password": self.settings.password})
        resp = self._send("POST", f"{self.settings.instance_url}/oauth_token.do", data=data, auth_retry=False)
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise ServiceNowError("OAuth token response did not include access_token")
        self._token = token
        self._token_expiry = time.monotonic() + float(payload.get("expires_in", 1800))
        self.session.headers["Authorization"] = f"Bearer {token}"

    # ---- transport --------------------------------------------------------------

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self._backoff_cap)
            except ValueError:
                pass
        delay = min(self._backoff_base * (2**attempt), self._backoff_cap)
        return delay + random.uniform(0, delay * 0.1)  # small jitter

    def _send(self, method: str, url: str, auth_retry: bool = True, **kwargs: Any) -> requests.Response:
        attempt = 0
        refreshed = False
        while True:
            try:
                resp = self.session.request(
                    method, url, timeout=self.settings.timeout, verify=self.settings.verify_tls, **kwargs
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self.settings.max_retries:
                    raise ServiceNowError(f"{method} {url} failed after {attempt + 1} attempts: {exc}") from exc
                delay = self._backoff(attempt, None)
                log.warning("transport error (%s); retrying in %.1fs", type(exc).__name__, delay)
                self._sleep(delay)
                attempt += 1
                continue

            if resp.status_code == 401 and auth_retry and self.settings.auth_mode == "oauth" and not refreshed:
                # token expired or revoked: fetch a new one once
                self._token = None
                self._ensure_token()
                refreshed = True
                continue
            if resp.status_code in RETRYABLE_STATUS and attempt < self.settings.max_retries:
                delay = self._backoff(attempt, resp.headers.get("Retry-After"))
                log.warning("HTTP %s from %s; retrying in %.1fs", resp.status_code, url.split("?")[0], delay)
                self._sleep(delay)
                attempt += 1
                continue
            if resp.status_code >= 400:
                raise ServiceNowError(f"{method} {url.split('?')[0]} returned HTTP {resp.status_code}")
            return resp

    # ---- Table API --------------------------------------------------------------

    def iter_table(
        self,
        table: str,
        query: str | None = None,
        fields: list[str] | None = None,
        max_records: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield records from ``/api/now/table/<table>`` page by page."""
        if not table.replace("_", "").isalnum():
            raise ValueError(f"invalid table name '{table}'")
        self._ensure_token()
        url = f"{self.settings.instance_url}/api/now/table/{table}"
        offset = 0
        yielded = 0
        limit = self.settings.page_size
        while True:
            params: dict[str, Any] = {
                "sysparm_limit": limit,
                "sysparm_offset": offset,
                "sysparm_exclude_reference_link": "true",
                "sysparm_display_value": "false",
            }
            if query:
                # ORDERBY keeps offset pagination stable while records change
                params["sysparm_query"] = f"{query}^ORDERBYsys_id"
            else:
                params["sysparm_query"] = "ORDERBYsys_id"
            if fields:
                params["sysparm_fields"] = ",".join(fields)
            resp = self._send("GET", url, params=params)
            page = resp.json().get("result", [])
            for record in page:
                yield record
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return
            if len(page) < limit:
                return
            offset += limit

    def fetch_dataset(
        self,
        ci_tables: list[str],
        ci_query: str | None = "install_status!=7",
        fields: list[str] | None = None,
        max_records: int | None = None,
    ) -> Dataset:
        """Fetch CIs from each table, then the relationships that touch them."""
        cis: dict[str, dict[str, Any]] = {}
        for table in ci_tables:
            for record in self.iter_table(table, ci_query, fields or DEFAULT_CI_FIELDS, max_records):
                ci = normalise_ci(record)
                ci.setdefault("sys_class_name", table)
                cis[ci["sys_id"]] = ci  # child tables overlap parents; keep one copy
        rels = [
            to_relationship(r)
            for r in self.iter_table("cmdb_rel_ci", None, REL_FIELDS)
            if r.get("parent") in cis or r.get("child") in cis
        ]
        log.info("fetched %d CIs and %d relationships", len(cis), len(rels))
        complete = set(ci_tables) == {"cmdb_ci"} and not max_records
        return Dataset(cis=list(cis.values()), relationships=rels, complete_scope=complete)
