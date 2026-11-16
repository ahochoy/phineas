data "aws_iam_policy_document" "worker_assume_role" {
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

resource "aws_iam_role" "worker_execution" {
  name               = "PhineasQuestionWorkerExecutionRole"
  description        = "Execution role for the Phineas question worker"
  assume_role_policy = data.aws_iam_policy_document.worker_assume_role.json
}

resource "aws_cloudwatch_log_group" "question_worker" {
  name              = "/aws/lambda/phineas-question-worker"
  retention_in_days = 7
}

data "aws_iam_policy_document" "worker_execution" {
  statement {
    sid    = "ConsumeQuestionJobs"
    effect = "Allow"

    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]

    resources = [aws_sqs_queue.question_jobs.arn]
  }

  statement {
    sid    = "ReadSessionsAndWriteJobs"
    effect = "Allow"

    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:PutItem",
      "dynamodb:ConditionCheckItem",
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
    sid    = "WriteWorkerLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = ["${aws_cloudwatch_log_group.question_worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "worker_execution" {
  name   = "PhineasQuestionWorkerExecution"
  role   = aws_iam_role.worker_execution.id
  policy = data.aws_iam_policy_document.worker_execution.json
}
