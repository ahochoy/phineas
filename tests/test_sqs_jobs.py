from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from phineas.jobs import JobMessage, QueueUnavailable
from phineas.questions import QuestionIntent
from phineas.sqs_jobs import SqsJobQueue


def test_sender_reuses_client_and_sends_only_safe_identifiers():
    message = JobMessage(session_id="opaque", job_id=uuid4(), intent=QuestionIntent.FEES)
    client = Mock()
    with patch("phineas.sqs_jobs.boto3.Session") as session:
        session.return_value.client.return_value = client
        queue = SqsJobQueue("https://sqs.example/queue")
        queue.enqueue(message)
        queue.enqueue(message)
        assert session.return_value.client.call_count == 1
    kwargs = client.send_message.call_args.kwargs
    assert kwargs == {"QueueUrl": "https://sqs.example/queue", "MessageBody": message.model_dump_json()}
    assert set(JobMessage.model_validate_json(kwargs["MessageBody"]).model_dump()) == {"session_id", "job_id", "intent"}


@pytest.mark.parametrize("failure", [
    EndpointConnectionError(endpoint_url="https://sqs.example"),
    ClientError({"Error": {"Code": "AccessDenied", "Message": "sensitive details"}}, "SendMessage"),
])
def test_send_failure_is_safe_and_retryable(failure):
    with patch("phineas.sqs_jobs.boto3.Session") as session:
        session.return_value.client.return_value.send_message.side_effect = failure
        with pytest.raises(QueueUnavailable) as error:
            SqsJobQueue("https://sqs.example/queue").enqueue(
                JobMessage(session_id="opaque", job_id=uuid4(), intent=QuestionIntent.FEES))
        assert "sensitive" not in str(error.value)
