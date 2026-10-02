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
