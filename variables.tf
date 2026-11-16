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

variable "api_image_digest" {
  description = "Verified ECR image digest deployed to the API Lambda."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.api_image_digest))
    error_message = "Provide a sha256 digest containing 64 lowercase hexadecimal characters."
  }
}

variable "worker_image_digest" {
  description = "Verified ECR image digest deployed to the question worker."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.worker_image_digest))
    error_message = "Provide a sha256 digest containing 64 lowercase hexadecimal characters."
  }
}

variable "demo_admissions_enabled" {
  description = "Allow new question jobs through the shared demo admission gate."
  type        = bool
  default     = false
  nullable    = false
}
