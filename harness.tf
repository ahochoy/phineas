resource "aws_bedrockagentcore_harness" "phineas" {
  harness_name          = "PhineasHarness"
  execution_role_arn    = aws_iam_role.harness_execution.arn
  environment_variables = {}

  model {
    bedrock_model_config {
      model_id   = "us.amazon.nova-micro-v1:0"
      api_format = "converse_stream"

      max_tokens  = 512
      temperature = 0.1
    }
  }

  system_prompt {
    text = file("${path.module}/prompts/narrative.txt")
  }

  max_iterations  = 3
  max_tokens      = 1024
  timeout_seconds = 60

  memory {
    disabled {}
  }

  environment {
    agentcore_runtime_environment {
      lifecycle_configuration {
        idle_runtime_session_timeout = 1800
        max_lifetime                 = 14400
      }

      network_configuration {
        network_mode = "PUBLIC"
      }
    }
  }

  depends_on = [
    aws_iam_role_policy.harness_execution,
  ]
}
