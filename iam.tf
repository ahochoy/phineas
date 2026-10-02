data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  nova_micro_inference_profile_arn = join(":", [
    "arn",
    data.aws_partition.current.partition,
    "bedrock",
    "us-east-2",
    data.aws_caller_identity.current.account_id,
    "inference-profile/us.amazon.nova-micro-v1:0",
  ])

  nova_micro_model_arns = [
    "arn:${data.aws_partition.current.partition}:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0",
    "arn:${data.aws_partition.current.partition}:bedrock:us-east-2::foundation-model/amazon.nova-micro-v1:0",
    "arn:${data.aws_partition.current.partition}:bedrock:us-west-2::foundation-model/amazon.nova-micro-v1:0",
  ]
}

data "aws_iam_policy_document" "harness_assume_role" {
  statement {
    sid     = "AllowAgentCoreHarness"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${data.aws_partition.current.partition}:bedrock-agentcore:us-east-2:${data.aws_caller_identity.current.account_id}:*"
      ]
    }
  }
}

resource "aws_iam_role" "harness_execution" {
  name               = "PhineasAgentCoreHarnessExecutionRole"
  description        = "Execution role for the Phineas AgentCore Harness"
  assume_role_policy = data.aws_iam_policy_document.harness_assume_role.json
}

data "aws_iam_policy_document" "harness_execution" {
  statement {
    sid    = "InvokeNovaMicro"
    effect = "Allow"

    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]

    resources = concat(
      [local.nova_micro_inference_profile_arn],
      local.nova_micro_model_arns,
    )
  }

  statement {
    sid    = "PullAgentCoreManagedImage"
    effect = "Allow"

    actions = [
      "ecr-public:GetAuthorizationToken",
    ]

    resources = ["*"]
  }

  statement {
    sid       = "GetECRPublicBearerToken"
    effect    = "Allow"
    actions   = ["sts:GetServiceBearerToken"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "sts:AWSServiceName"
      values   = ["ecr-public.amazonaws.com"]
    }
  }

  statement {
    sid    = "WriteAgentCoreTraces"
    effect = "Allow"

    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
    ]

    resources = ["*"]
  }

  statement {
    sid    = "ManageAgentCoreRuntimeLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogGroup",
      "logs:DescribeLogStreams",
    ]

    resources = [
      "arn:${data.aws_partition.current.partition}:logs:us-east-2:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"
    ]
  }

  statement {
    sid    = "WriteAgentCoreRuntimeLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = [
      "arn:${data.aws_partition.current.partition}:logs:us-east-2:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
    ]
  }

  statement {
    sid       = "DescribeLogGroups"
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["arn:${data.aws_partition.current.partition}:logs:us-east-2:${data.aws_caller_identity.current.account_id}:log-group:*"]
  }

  statement {
    sid       = "ConfigureAgentCoreLogDelivery"
    effect    = "Allow"
    actions   = ["logs:PutResourcePolicy"]
    resources = ["*"]
  }

  statement {
    sid       = "PublishAgentCoreMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }
}

resource "aws_iam_role_policy" "harness_execution" {
  name   = "PhineasAgentCoreHarnessExecution"
  role   = aws_iam_role.harness_execution.id
  policy = data.aws_iam_policy_document.harness_execution.json
}
