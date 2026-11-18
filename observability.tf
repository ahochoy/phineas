resource "aws_sns_topic" "operational_alerts" {
  name = "phineas-operational-alerts"
}

resource "aws_sns_topic_subscription" "operational_email" {
  topic_arn = aws_sns_topic.operational_alerts.arn
  protocol  = "email"
  endpoint  = var.operational_alert_email
}

resource "aws_cloudwatch_log_metric_filter" "terminal_failures" {
  name           = "phineas-question-terminal-failures"
  log_group_name = aws_cloudwatch_log_group.question_worker.name

  pattern = "{ $.event = \"question_delivery\" && $.schema_version = 1 && $.outcome = \"terminal_failed\" }"

  metric_transformation {
    name          = "QuestionTerminalFailureObservations"
    namespace     = "Phineas/Worker"
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "terminal_failures" {
  alarm_name        = "phineas-question-terminal-failures"
  alarm_description = "At least one terminal question-job failure observation."

  namespace   = aws_cloudwatch_log_metric_filter.terminal_failures.metric_transformation[0].namespace
  metric_name = aws_cloudwatch_log_metric_filter.terminal_failures.metric_transformation[0].name
  statistic   = "Sum"
  unit        = "Count"

  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.operational_alerts.arn]
}

data "aws_iam_policy_document" "operational_alerts" {
  statement {
    sid     = "AllowPhineasOperationalAlarms"
    effect  = "Allow"
    actions = ["sns:Publish"]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    resources = [aws_sns_topic.operational_alerts.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values = [
        aws_cloudwatch_metric_alarm.terminal_failures.arn,
        aws_cloudwatch_metric_alarm.question_jobs_dlq.arn,
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "operational_alerts" {
  arn    = aws_sns_topic.operational_alerts.arn
  policy = data.aws_iam_policy_document.operational_alerts.json
}

resource "aws_cloudwatch_metric_alarm" "question_jobs_dlq" {
  alarm_name        = "phineas-question-jobs-dlq-nonempty"
  alarm_description = "At least one visible message requires investigation in the question jobs DLQ."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  statistic   = "Maximum"

  dimensions = {
    QueueName = aws_sqs_queue.question_jobs_dlq.name
  }

  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.operational_alerts.arn]
}
