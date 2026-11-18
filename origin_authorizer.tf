resource "aws_lambda_function" "origin_authorizer" {
  function_name = "phineas-origin-authorizer"
  description   = "Authenticates Cloudflare requests to the Phineas origin"

  filename         = "${path.module}/.build/origin-authorizer.zip"
  source_code_hash = filebase64sha256("${path.module}/.build/origin-authorizer.zip")

  runtime       = "python3.14"
  handler       = "origin_authorizer.lambda_handler"
  architectures = ["arm64"]
  memory_size   = 128
  timeout       = 10

  role = aws_iam_role.origin_authorizer_execution.arn

  environment {
    variables = {
      PHINEAS_ORIGIN_SECRET_ARN = aws_secretsmanager_secret.origin_auth.arn
    }
  }

  depends_on = [
    aws_iam_role_policy.origin_authorizer_execution,
    aws_cloudwatch_log_group.origin_authorizer,
  ]
}
