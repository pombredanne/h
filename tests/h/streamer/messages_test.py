from unittest import mock
from unittest.mock import Mock, create_autospec, sentinel

import pytest
from gevent.queue import Queue
from h_matchers import Any
from pyramid import security
from pyramid.request import Request

from h.security import Permission
from h.streamer import messages
from h.streamer.websocket import WebSocket


class TestProcessMessages:
    def test_it_creates_and_runs_a_consumer(self, Consumer, realtime, work_queue):
        settings = {}
        messages.process_messages(
            settings, "routing_key", work_queue, raise_error=False
        )

        realtime.get_connection.assert_called_once_with(settings)
        Consumer.assert_called_once_with(
            connection=realtime.get_connection.return_value,
            routing_key="routing_key",
            handler=Any(),
        )
        consumer = Consumer.return_value
        consumer.run.assert_called_once_with()

    def test_it_puts_message_on_queue(self, _handler, work_queue):
        _handler({"foo": "bar"})

        result = work_queue.get_nowait()
        assert result.topic == "routing_key"  # Set by _handler fixture
        assert result.payload == {"foo": "bar"}

    def test_it_handles_a_full_queue(self, _handler, work_queue):
        work_queue.put(messages.Message(topic="queue_is_full", payload={}))

        _handler({"foo": "bar"})

        result = work_queue.get_nowait()
        assert result.topic == "queue_is_full"

    def test_it_raises_if_the_consumer_exits(self, work_queue):
        with pytest.raises(RuntimeError):
            messages.process_messages({}, "routing_key", work_queue)

    @pytest.fixture
    def _handler(self, Consumer, work_queue):
        messages.process_messages({}, "routing_key", work_queue, raise_error=False)
        return Consumer.call_args[1]["handler"]

    @pytest.fixture(autouse=True)
    def Consumer(self, patch):
        return patch("h.streamer.messages.Consumer")

    @pytest.fixture(autouse=True)
    def realtime(self, patch):
        return patch("h.streamer.messages.realtime")

    @pytest.fixture
    def work_queue(self):
        return Queue(maxsize=1)


class TestHandleMessage:
    def test_calls_handler_with_list_of_sockets(self, websocket, registry):
        handler = Mock(return_value=None)
        session = sentinel.db_session
        message = messages.Message(topic="foo", payload={"foo": "bar"})
        websocket.instances = [sentinel.socket_1, sentinel.socket_2]

        messages.handle_message(
            message, registry, session, topic_handlers={"foo": handler}
        )

        handler.assert_called_once_with(
            message.payload,
            websocket.instances,
            Any.object.of_type(Request).with_attrs({"registry": registry}),
            session,
        )

    def test_it_raises_RuntimeError_for_bad_topics(self, registry):
        message = messages.Message(topic="unknown", payload={})
        topic_handlers = {"known": sentinel.handler}

        with pytest.raises(RuntimeError):
            messages.handle_message(
                message,
                registry,
                session=sentinel.db_session,
                topic_handlers=topic_handlers,
            )

    @pytest.fixture
    def registry(self, pyramid_request):
        return pyramid_request.registry

    @pytest.fixture
    def websocket(self, patch):
        return patch("h.streamer.websocket.WebSocket")


@pytest.mark.usefixtures("nipsa_service", "user_service", "links_service")
class TestHandleAnnotationEvent:
    def test_it_fetches_the_annotation(
        self, fetch_annotation, handle_annotation_event, session, message
    ):
        handle_annotation_event(message=message, session=session)

        fetch_annotation.assert_called_once_with(session, message["annotation_id"])

    def test_it_skips_notification_when_fetch_failed(
        self, fetch_annotation, handle_annotation_event
    ):
        fetch_annotation.return_value = None

        result = handle_annotation_event()

        assert result is None

    def test_it_serializes_the_annotation(
        self,
        handle_annotation_event,
        fetch_annotation,
        links_service,
        user_service,
        AnnotationJSONPresenter,
    ):
        handle_annotation_event()

        AnnotationJSONPresenter.assert_called_once_with(
            fetch_annotation.return_value,
            links_service=links_service,
            user_service=user_service,
        )
        assert AnnotationJSONPresenter.return_value.asdict.called

    @pytest.mark.parametrize("action", ["create", "update", "delete"])
    def test_notification_format(
        self, handle_annotation_event, action, message, socket, AnnotationJSONPresenter
    ):
        message["action"] = action

        handle_annotation_event(sockets=[socket])

        if action == "delete":
            expected_payload = {"id": message["annotation_id"]}
        else:
            expected_payload = AnnotationJSONPresenter.return_value.asdict.return_value

        socket.send_json.assert_called_once_with(
            {
                "payload": [expected_payload],
                "type": "annotation-notification",
                "options": {"action": action},
            }
        )

    def test_it_filters_the_sockets(
        self,
        handle_annotation_event,
        SocketFilter,
        fetch_annotation,
        socket,
        db_session,
    ):

        handle_annotation_event(sockets=[socket], session=db_session)

        SocketFilter.matching.assert_called_once_with(
            [socket], fetch_annotation.return_value, db_session
        )

    def test_no_send_for_sender_socket(self, handle_annotation_event, socket, message):
        message["src_client_id"] = socket.client_id

        handle_annotation_event(message=message, sockets=[socket])

        socket.send_json.assert_not_called()

    def test_no_send_if_filter_does_not_match(
        self, handle_annotation_event, socket, SocketFilter
    ):
        SocketFilter.matching.side_effect = None
        SocketFilter.matching.return_value = iter(())
        handle_annotation_event(sockets=[socket])

        socket.send_json.assert_not_called()

    @pytest.mark.parametrize(
        "userid,can_see",
        (
            ("other_user", False),
            ("nipsaed_user", True),
        ),
    )
    def test_nipsaed_content_visibility(
        self,
        handle_annotation_event,
        userid,
        can_see,
        socket,
        nipsa_service,
        fetch_annotation,
    ):
        """Should return None if the annotation is from a NIPSA'd user."""
        nipsa_service.is_flagged.return_value = True
        fetch_annotation.return_value.userid = "nipsaed_user"
        socket.authenticated_userid = userid

        handle_annotation_event(sockets=[socket])

        assert bool(socket.send_json.call_count) == can_see

    @pytest.mark.parametrize(
        "user_principals,can_see",
        (
            [[], False],
            [["wrong_principal"], False],
            [["principal"], True],
            [["principal", "user_noise"], True],
        ),
    )
    def test_visibility_is_based_on_acl(
        self,
        handle_annotation_event,
        user_principals,
        can_see,
        AnnotationContext,
        principals_allowed_by_permission,
        socket,
    ):
        principals_allowed_by_permission.return_value = ["principal", "acl_noise"]
        socket.effective_principals = user_principals

        handle_annotation_event(sockets=[socket])

        principals_allowed_by_permission.assert_called_with(
            AnnotationContext.return_value, Permission.Annotation.READ_REALTIME_UPDATES
        )
        assert bool(socket.send_json.call_count) == can_see

    @pytest.fixture
    def handle_annotation_event(self, message, socket, pyramid_request, session):
        def handle_annotation_event(
            message=message, sockets=None, request=pyramid_request, session=session
        ):
            if sockets is None:
                sockets = [socket]

            return messages.handle_annotation_event(message, sockets, request, session)

        return handle_annotation_event

    @pytest.fixture
    def pyramid_request(self, pyramid_request):
        pyramid_request.registry.settings = {
            "h.app_url": "http://streamer",
            "h.authority": "example.org",
        }

        return pyramid_request

    @pytest.fixture
    def session(self):
        return sentinel.db_session

    @pytest.fixture
    def message(self, fetch_annotation):
        return {
            # This is a bit backward from how things really work, but it
            # ensures the id we look up gives us an annotation that matches
            "annotation_id": fetch_annotation.return_value.id,
            "action": "update",
            "src_client_id": "source_socket",
        }

    @pytest.fixture(autouse=True)
    def fetch_annotation(self, factories, patch):
        fetch = patch("h.streamer.messages.storage.fetch_annotation")
        fetch.return_value = factories.Annotation()
        return fetch

    @pytest.fixture
    def principals_allowed_by_permission(self, patch):
        return patch("h.streamer.messages.principals_allowed_by_permission")

    @pytest.fixture
    def AnnotationContext(self, patch):
        return patch("h.streamer.messages.AnnotationContext")

    @pytest.fixture(autouse=True)
    def AnnotationJSONPresenter(self, patch):
        return patch("h.streamer.messages.presenters.AnnotationJSONPresenter")

    @pytest.fixture(autouse=True)
    def SocketFilter(self, patch):
        SocketFilter = patch("h.streamer.messages.SocketFilter")
        SocketFilter.matching.side_effect = (
            lambda sockets, annotation, db_session: iter(sockets)
        )
        return SocketFilter


class TestHandleUserEvent:
    def test_sends_session_change_when_joining_or_leaving_group(self, socket, message):
        socket.authenticated_userid = message["userid"]

        messages.handle_user_event(message, [socket, socket], None, None)

        reply = {
            "type": "session-change",
            "action": "group-join",
            "model": message["session_model"],
        }

        assert socket.send_json.call_args_list == [
            mock.call(reply),
            mock.call(reply),
        ]

    def test_no_send_when_socket_is_not_event_users(self, socket, message):
        """Don't send session-change events if the event user is not the socket user."""
        message["userid"] = "amy"
        socket.authenticated_userid = "bob"

        messages.handle_user_event(message, [socket], None, None)

        socket.send_json.assert_not_called()

    @pytest.fixture
    def message(self):
        return {
            "type": "group-join",
            "userid": "amy",
            "group": "groupid",
            "session_model": sentinel.session_model,
        }


@pytest.fixture
def socket():
    socket = create_autospec(WebSocket, instance=True)
    socket.effective_principals = [security.Everyone, "group:__world__"]
    return socket
