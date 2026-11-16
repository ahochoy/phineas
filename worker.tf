resource "aws_lambda_function" "question_worker" {
  function_name = "phineas-question-worker"
  description   = "Processes bounded Phineas question jobs from SQS"

  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.api.repository_url}@${var.worker_image_digest}"
  architectures = ["arm64"]

  role        = aws_iam_role.worker_execution.arn
  memory_size = 512
  timeout     = 120

  reserved_concurrent_executions = -1

  environment {
    variables = {
      PHINEAS_SESSIONS_TABLE = aws_dynamodb_table.sessions.name
      PHINEAS_HARNESS_ARN    = aws_bedrockagentcore_harness.phineas.arn
    }
  }

  depends_on = [
    aws_iam_role_policy.worker_execution,
    aws_cloudwatch_log_group.question_worker,
    aws_ecr_repository_policy.api_image_retrieval,
  ]
}

resource "aws_lambda_event_source_mapping" "question_jobs" {
  event_source_arn = aws_sqs_queue.question_jobs.arn
  function_name    = aws_lambda_function.question_worker.arn
  enabled          = true

  batch_size                         = 1
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 2
  }

  depends_on = [
    aws_iam_role_policy.worker_execution,
    aws_sqs_queue_redrive_allow_policy.question_jobs,
  ]
}
