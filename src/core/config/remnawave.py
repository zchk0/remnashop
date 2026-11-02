from typing import Literal
from urllib.parse import urlsplit

from httpx import URL, Cookies, InvalidURL
from pydantic import SecretStr, field_validator
from pydantic_core.core_schema import FieldValidationInfo

from src.core.utils.validators import is_valid_domain

from .base import BaseConfig
from .validators import validate_not_change_me


class RemnawaveConfig(BaseConfig, env_prefix="REMNAWAVE_"):
    api_version: Literal[2, 3] = 2
    host: SecretStr = SecretStr("http://remnawave:3000")
    token: SecretStr
    caddy_token: SecretStr = SecretStr("")
    cf_client_id: SecretStr = SecretStr("")
    cf_client_secret: SecretStr = SecretStr("")
    webhook_secret: SecretStr
    cookie: SecretStr = SecretStr("")

    @field_validator("api_version", mode="before")
    @classmethod
    def parse_api_version(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() in {"2", "3"}:
            return int(value.strip())
        return value

    @property
    def is_external(self) -> bool:
        return self.url.get_secret_value().startswith("https://")

    @property
    def url(self) -> SecretStr:
        return self.urls[0]

    @property
    def urls(self) -> tuple[SecretStr, ...]:
        return self._parse_urls(self.host)

    @staticmethod
    def _parse_urls(value: SecretStr) -> tuple[SecretStr, ...]:
        urls = []
        for host in value.get_secret_value().split(","):
            clean_host = host.strip()
            if not clean_host or any(char.isspace() for char in clean_host):
                raise ValueError("REMNAWAVE_HOST must contain comma-separated hosts")

            if "://" in clean_host:
                final_url = clean_host
            elif is_valid_domain(clean_host.rstrip("/")):
                final_url = f"https://{clean_host}"
            else:
                final_url = f"http://{clean_host}"

            try:
                url = URL(final_url)
            except InvalidURL:
                raise ValueError("Invalid URL in REMNAWAVE_HOST") from None
            if (
                url.scheme not in {"http", "https"}
                or not url.host
                or url.userinfo
                or url.query
                or url.fragment
            ):
                raise ValueError("REMNAWAVE_HOST must contain HTTP(S) hosts without credentials")
            if url.scheme == "http" and urlsplit(final_url).port is None:
                url = url.copy_with(port=3000)

            normalized = SecretStr(str(url).rstrip("/"))
            if normalized not in urls:
                urls.append(normalized)

        return tuple(urls)

    @field_validator("host")
    @classmethod
    def validate_host(cls, field: SecretStr) -> SecretStr:
        cls._parse_urls(field)
        return field

    @property
    def cookies(self) -> Cookies:
        raw_cookie = self.cookie.get_secret_value()
        cookies = Cookies()

        if raw_cookie and "=" in raw_cookie:
            key, value = raw_cookie.split("=", 1)
            cookies.set(key.strip(), value.strip())

        return cookies

    @field_validator("token")
    @classmethod
    def validate_remnawave_token(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)
        return field

    @field_validator("webhook_secret")
    @classmethod
    def validate_remnawave_webhook_secret(
        cls,
        field: SecretStr,
        info: FieldValidationInfo,
    ) -> SecretStr:
        validate_not_change_me(field, info)
        return field

    @field_validator("cookie")
    @classmethod
    def validate_cookie(cls, field: SecretStr) -> SecretStr:
        cookie = field.get_secret_value()

        if not cookie:
            return field

        cookie = cookie.strip()

        if "=" not in cookie or cookie.startswith("=") or cookie.endswith("="):
            raise ValueError("REMNAWAVE_COOKIE must be in 'key=value' format")

        return field
