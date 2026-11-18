data "aws_iam_policy_document" "origin_authorizer_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "origin_authorizer_execution" {
  name        = "PhineasOriginAuthorizerExecutionRole"
  description = "Execution role for the Phineas origin authorizer"

  assume_role_policy = data.aws_iam_policy_document.origin_authorizer_assume_role.json
}

resource "aws_cloudwatch_log_group" "origin_authorizer" {
  name              = "/aws/lambda/phineas-origin-authorizer"
  retention_in_days = 7
}

data "aws_iam_policy_document" "origin_authorizer_execution" {
  statement {
    sid       = "ReadOriginCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.origin_auth.arn]
  }

  statement {
    sid    = "WriteAuthorizerLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = ["${aws_cloudwatch_log_group.origin_authorizer.arn}:*"]
  }
}

resource "aws_iam_role_policy" "origin_authorizer_execution" {
  name   = "PhineasOriginAuthorizerExecution"
  role   = aws_iam_role.origin_authorizer_execution.id
  policy = data.aws_iam_policy_document.origin_authorizer_execution.json
}
