from datetime import datetime, timedelta

import factory

from h import models, security
from h.services.developer_token import PREFIX as DEVELOPER_TOKEN_PREFIX
from h.services.oauth_provider import ACCESS_TOKEN_PREFIX, REFRESH_TOKEN_PREFIX

from .auth_client import AuthClient
from .base import FAKER, ModelFactory


class DeveloperToken(ModelFactory):
    class Meta:
        model = models.Token
        sqlalchemy_session_persistence = "flush"

    userid = factory.LazyAttribute(
        lambda _: (
            "acct:" + FAKER.user_name() + "@example.com"  # pylint:disable=no-member
        )
    )
    value = factory.LazyAttribute(
        lambda _: (DEVELOPER_TOKEN_PREFIX + security.token_urlsafe())
    )


class OAuth2Token(ModelFactory):
    class Meta:
        model = models.Token
        sqlalchemy_session_persistence = "flush"

    userid = factory.LazyAttribute(
        lambda _: (
            "acct:" + FAKER.user_name() + "@example.com"  # pylint:disable=no-member
        )
    )
    value = factory.LazyAttribute(
        lambda _: (ACCESS_TOKEN_PREFIX + security.token_urlsafe())
    )
    refresh_token = factory.LazyAttribute(
        lambda _: (REFRESH_TOKEN_PREFIX + security.token_urlsafe())
    )
    expires = factory.LazyAttribute(lambda _: (datetime.utcnow() + timedelta(hours=1)))
    refresh_token_expires = factory.LazyAttribute(
        lambda _: (datetime.utcnow() + timedelta(days=7))
    )
    authclient = factory.SubFactory(AuthClient)
