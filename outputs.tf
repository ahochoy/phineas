output "phineas_harness_id" {
  description = "Unique identifier of the Phineas AgentCore Harness."
  value       = aws_bedrockagentcore_harness.phineas.harness_id
}

output "phineas_harness_arn" {
  description = "ARN used when invoking the Phineas AgentCore Harness."
  value       = aws_bedrockagentcore_harness.phineas.arn
}

output "phineas_harness_execution_role_arn" {
  description = "IAM execution role assumed by the Phineas Harness."
  value       = aws_iam_role.harness_execution.arn
}

output "sessions_table_name" {
  description = "DynamoDB table storing short-lived sanitized sessions."
  value       = aws_dynamodb_table.sessions.name
}

output "sessions_table_arn" {
  description = "ARN used to scope application session-storage permissions."
  value       = aws_dynamodb_table.sessions.arn
}

output "api_repository_url" {
  description = "ECR repository URL used to tag and push application images."
  value       = aws_ecr_repository.api.repository_url
}

output "api_repository_arn" {
  description = "ECR repository ARN used for permission scoping."
  value       = aws_ecr_repository.api.arn
}

output "api_function_name" {
  description = "Lambda function name used for private invocation tests."
  value       = aws_lambda_function.api.function_name
}
