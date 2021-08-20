from pyramid.interfaces import ISecurityPolicy
from zope.interface import implementer

from h.security import Identity
from h.security.policy._identity_base import IdentityBasedPolicy


@implementer(ISecurityPolicy)
class TokenPolicy(IdentityBasedPolicy):
    """
    A bearer token authentication policy.

    This policy uses a bearer token which is validated against Token objects
    in the DB. This can come from the `request.auth_token` (from
    `h.auth.tokens.auth_token`) or in the case of Websocket requests the
    GET parameter `access_token`.
    """

    def identity(self, request):
        """
        Get an Identity object for valid credentials.

        Validate the token from the request by matching them to Token records
        in the DB.

        :param request: Pyramid request to inspect
        :returns: An `Identity` object if the login is authenticated or None
        """
        token_svc = request.find_service(name="auth_token")
        token_str = None

        if self._is_ws_request(request):
            token_str = request.GET.get("access_token", None)

        if token_str is None:
            token_str = self.get_bearer_token(request)

        if token_str is None:
            return None

        token = token_svc.validate(token_str)
        if token is None:
            return None

        user = request.find_service(name="user").fetch(token.userid)
        if user is None:
            return None

        return Identity(user=user)




    @staticmethod
    def _is_ws_request(request):
        return request.path == "/ws"
