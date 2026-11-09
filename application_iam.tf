data "aws_iam_policy_document" "api_assume_role" {
  statement {
    sid     = "AllowLambda"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api_execution" {
  name               = "PhineasApiExecutionRole"
  description        = "Execution role for the Phineas FastAPI application"
  assume_role_policy = data.aws_iam_policy_document.api_assume_role.json
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/phineas-api"
  retention_in_days = 7
}

data "aws_iam_policy_document" "api_execution" {
  statement {
    sid    = "ManageSessionRecords"
    effect = "Allow"

    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
    ]

    resources = [aws_dynamodb_table.sessions.arn]
  }

  statement {
    sid    = "InvokePhineasHarness"
    effect = "Allow"

    actions = [
      "bedrock-agentcore:InvokeHarness",
      "bedrock-agentcore:InvokeAgentRuntime",
    ]

    resources = [aws_bedrockagentcore_harness.phineas.arn]
  }

  statement {
    sid    = "WriteApplicationLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
}

resource "aws_iam_role_policy" "api_execution" {
  name   = "PhineasApiExecution"
  role   = aws_iam_role.api_execution.id
  policy = data.aws_iam_policy_document.api_execution.json
}
