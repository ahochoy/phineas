variable "monthly_budget_amount" {
  description = "Maximum planed AWS spend per month for Phineas."
  type        = number
  default     = 20

  validation {
    condition     = var.monthly_budget_amount > 0
    error_message = "The monthly budget amoutn must be greater than zero."
  }
}

variable "budget_alert_email" {
  description = "Email address that researves AWS budget notifications."
  type        = string
}
