resource "aws_sqs_queue" "question_jobs_dlq" {
  name = "phineas-question-jobs-dlq"

  message_retention_seconds = 14400
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "question_jobs" {
  name = "phineas-question-jobs"

  visibility_timeout_seconds = 720
  message_retention_seconds  = 3600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.question_jobs_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "question_jobs" {
  queue_url = aws_sqs_queue.question_jobs_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.question_jobs.arn]
  })
}
