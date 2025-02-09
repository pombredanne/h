from unittest.mock import patch, sentinel

import pytest
from pyramid.httpexceptions import HTTPBadRequest

from h.exceptions import InvalidUserId
from h.traversal.user import UserByIDRoot, UserByNameRoot, UserContext, UserRoot


class TestUserContext:
    def test_acl_matching_user(self, factories, ACL):
        user = factories.User()

        acl = UserContext(user).__acl__()

        ACL.for_user.assert_called_once_with(user)
        assert acl == ACL.for_user.return_value

    @pytest.fixture
    def ACL(self, patch):
        return patch("h.traversal.user.ACL")


@pytest.mark.usefixtures("user_service")
class TestUserRoot:
    def test_acl_matching_user(self, root, ACL):
        acl = root.__acl__()

        ACL.for_user.assert_called_once_with(user=None)
        assert acl == ACL.for_user.return_value

    def test_get_user_context(self, root, user_service, UserContext):
        user = root.get_user_context(sentinel.userid, sentinel.authority)

        user_service.fetch.assert_called_once_with(sentinel.userid, sentinel.authority)

        UserContext.assert_called_with(user_service.fetch.return_value)
        assert user == UserContext.return_value

    def test_get_user_context_raises_if_the_user_does_not_exist(
        self, root, user_service
    ):
        user_service.fetch.return_value = None

        with pytest.raises(KeyError):
            root.get_user_context(sentinel.userid, sentinel.authority)

    def test_get_user_context_raises_if_the_userid_is_invalid(self, root, user_service):
        user_service.fetch.side_effect = InvalidUserId("user_id")

        with pytest.raises(HTTPBadRequest):
            root.get_user_context(sentinel.bad_username, authority=None)

    @pytest.fixture(autouse=True)
    def UserContext(self, patch):
        return patch("h.traversal.user.UserContext")

    @pytest.fixture
    def root(self, pyramid_request):
        return UserRoot(pyramid_request)


@pytest.mark.usefixtures("user_service")
class TestUserByNameRoot:
    @pytest.mark.parametrize("returned_authority", (None, sentinel.client_authority))
    def test_it_fetches_the_requested_user(
        self, pyramid_request, root, client_authority, returned_authority
    ):
        client_authority.return_value = returned_authority

        context = root[sentinel.username]

        client_authority.assert_called_once_with(pyramid_request)
        root.get_user_context.assert_called_once_with(
            sentinel.username,
            authority=client_authority.return_value
            or pyramid_request.default_authority,
        )
        assert context == root.get_user_context.return_value

    @pytest.fixture(autouse=True)
    def client_authority(self, patch):
        return patch("h.traversal.user.client_authority")

    @pytest.fixture
    def root(self, pyramid_request):
        root = UserByNameRoot(pyramid_request)

        with patch.object(root, "get_user_context"):
            yield root


@pytest.mark.usefixtures("user_service")
class TestUserByIDRoot:
    def test_it_fetches_the_requested_user(self, root):
        context = root[sentinel.userid]

        root.get_user_context.assert_called_once_with(sentinel.userid, authority=None)

        assert context == root.get_user_context.return_value

    @pytest.fixture
    def root(self, pyramid_request):
        root = UserByIDRoot(pyramid_request)
        with patch.object(root, "get_user_context"):
            yield root


@pytest.fixture
def ACL(patch):
    return patch("h.traversal.user.ACL")
