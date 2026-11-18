resource "aws_lambda_function" "api" {
  function_name = "phineas-api"
  description   = "Phineas synthetic financial-analysis API"

  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.api.repository_url}@${var.api_image_digest}"
  architectures = ["arm64"]

  role        = aws_iam_role.api_execution.arn
  memory_size = 512
  timeout     = 120

  reserved_concurrent_executions = -1

  environment {
    variables = {
      PHINEAS_SESSIONS_TABLE     = aws_dynamodb_table.sessions.name
      PHINEAS_HARNESS_ARN        = aws_bedrockagentcore_harness.phineas.arn
      PHINEAS_QUESTION_QUEUE_URL = aws_sqs_queue.question_jobs.url
      AWS_LWA_REMOVE_BASE_PATH   = "/public"
    }
  }

  depends_on = [
    aws_iam_role_policy.api_execution,
    aws_cloudwatch_log_group.api,
    aws_ecr_repository_policy.api_image_retrieval,
  ]
}
