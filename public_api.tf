resource "aws_apigatewayv2_api" "public" {
  name          = "phineas-public"
  description   = "Protected origin for the Phineas synthetic demo"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_authorizer" "origin" {
  api_id          = aws_apigatewayv2_api.public.id
  name            = "phineas-origin"
  authorizer_type = "REQUEST"
  authorizer_uri  = aws_lambda_function.origin_authorizer.invoke_arn

  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  identity_sources                  = ["$request.header.x-phineas-origin-token"]
  authorizer_result_ttl_in_seconds  = 0
}

resource "aws_lambda_permission" "origin_authorizer_gateway" {
  statement_id  = "AllowPhineasGatewayAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.origin_authorizer.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "${aws_apigatewayv2_api.public.execution_arn}/authorizers/${aws_apigatewayv2_authorizer.origin.id}"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id = aws_apigatewayv2_api.public.id

  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 10000
}

locals {
  public_api_routes = toset([
    "GET /health",
    "GET /samples",
    "GET /samples/{sample_id}/preview",
    "GET /questions/suggestions",
    "POST /sessions",
    "GET /sessions/{session_id}/report",
    "POST /sessions/{session_id}/question-jobs",
    "GET /sessions/{session_id}/jobs/{job_id}",
    "DELETE /sessions/{session_id}",
  ])
}

resource "aws_apigatewayv2_route" "public" {
  for_each = local.public_api_routes

  api_id    = aws_apigatewayv2_api.public.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.origin.id
}

resource "aws_lambda_permission" "public_api_gateway" {
  statement_id  = "AllowPhineasPublicGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"

  source_account = data.aws_caller_identity.current.account_id
  source_arn     = "${aws_apigatewayv2_api.public.execution_arn}/public/*/*"
}

resource "aws_cloudwatch_log_group" "public_api" {
  name              = "/aws/apigateway/phineas-public"
  retention_in_days = 7
}

resource "aws_apigatewayv2_stage" "public" {
  api_id      = aws_apigatewayv2_api.public.id
  name        = "public"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = 5
    throttling_burst_limit = 10
  }

  route_settings {
    route_key              = "POST /sessions"
    throttling_rate_limit  = 0.5
    throttling_burst_limit = 2
  }

  route_settings {
    route_key              = "POST /sessions/{session_id}/question-jobs"
    throttling_rate_limit  = 1
    throttling_burst_limit = 2
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.public_api.arn

    format = jsonencode({
      requestId = "$context.requestId"
      status    = "$context.status"
    })
  }

  depends_on = [
    aws_apigatewayv2_route.public,
    aws_lambda_permission.public_api_gateway,
    aws_lambda_permission.origin_authorizer_gateway,
  ]
}
