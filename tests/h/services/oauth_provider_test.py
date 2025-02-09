from unittest import mock

import pytest
from oauthlib.common import Request as OAuthRequest
from oauthlib.oauth2 import InvalidRequestError

from h.models import Token
from h.oauth.errors import InvalidRefreshTokenError
from h.services.oauth_provider import (
    OAuthProviderService,
    oauth_provider_service_factory,
)


@pytest.mark.usefixtures("validator_service", "user_service")
class TestOAuthProviderService:
    def test_load_client_id_sets_client_id_from_refresh_token(
        self, svc, oauth_request, factories, validator_service
    ):
        token_1, token_2 = factories.OAuth2Token(), factories.OAuth2Token()
        oauth_request.refresh_token = token_2.refresh_token

        def fake_find_refresh_token(refresh_token):
            if refresh_token == token_1.refresh_token:
                return token_1
            if refresh_token == token_2.refresh_token:
                return token_2

            return None

        validator_service.find_refresh_token.side_effect = fake_find_refresh_token

        assert oauth_request.client_id is None
        svc.load_client_id_from_refresh_token(oauth_request)
        assert oauth_request.client_id == token_2.authclient.id

    def test_load_client_id_skips_setting_client_id_when_not_refresh_token(
        self, svc, oauth_request, factories, validator_service
    ):
        token = factories.OAuth2Token()

        def fake_find_refresh_token(refresh_token):
            if refresh_token == token.refresh_token:
                return token
            return None

        validator_service.find_refresh_token.side_effect = fake_find_refresh_token

        svc.load_client_id_from_refresh_token(oauth_request)
        assert oauth_request.client_id is None

    def test_load_client_id_raises_for_missing_refresh_token(
        self, svc, oauth_request, validator_service
    ):
        validator_service.find_refresh_token.return_value = None
        oauth_request.refresh_token = "missing"

        with pytest.raises(InvalidRefreshTokenError):
            svc.load_client_id_from_refresh_token(oauth_request)

    def test_generate_access_token(self, svc, token_urlsafe):
        token_urlsafe.return_value = "very-secret"
        assert svc.generate_access_token(None) == "5768-very-secret"

    def test_generate_refresh_token(self, svc, token_urlsafe):
        token_urlsafe.return_value = "top-secret"
        assert svc.generate_refresh_token(None) == "4657-top-secret"

    def test_validate_revocation_request_adds_revoke_marker(self, svc, oauth_request):
        try:
            svc.validate_revocation_request(oauth_request)

        except InvalidRequestError:
            # Not here to test this
            pass

        finally:
            assert oauth_request.h_revoke_request is True

    def test_validate_revocation_request_looks_up_token(
        self, svc, oauth_request, token
    ):
        oauth_request.token = mock.sentinel.token
        svc.oauth_validator.find_token.return_value = token
        oauth_request.http_method = "POST"

        svc.validate_revocation_request(oauth_request)

        svc.oauth_validator.find_token.assert_called_once_with(mock.sentinel.token)
        assert oauth_request.client_id == token.authclient.id

    @pytest.fixture
    def token(self):
        return mock.create_autospec(Token, instance=True)

    @pytest.fixture
    def svc(self, pyramid_request):
        return oauth_provider_service_factory(None, pyramid_request)

    @pytest.fixture
    def token_urlsafe(self, patch):
        return patch("h.services.oauth_provider.token_urlsafe")

    @pytest.fixture
    def oauth_request(self):
        return OAuthRequest("/")


@pytest.mark.usefixtures("validator_service", "user_service")
class TestOAuthProviderServiceFactory:
    def test_it_returns_oauth_provider_service(self, pyramid_request):
        svc = oauth_provider_service_factory(None, pyramid_request)
        assert isinstance(svc, OAuthProviderService)


@pytest.fixture
def validator_service(pyramid_config):
    svc = mock.Mock()
    pyramid_config.register_service(svc, name="oauth_validator")
    return svc
