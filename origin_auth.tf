resource "aws_secretsmanager_secret" "origin_auth" {
  name                    = "phineas/origin-auth"
  description             = "Authenticates the Cloudflare Worker to the Phineas API"
  recovery_window_in_days = 7
}
