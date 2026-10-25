variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-west-2"
}

variable "environment" {
  description = "Deployment environment (dev / staging / production)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "environment must be one of: dev, staging, production"
  }
}

variable "project_name" {
  description = "Project name prefix used for all resource names"
  type        = string
  default     = "financial-dataops"
}

variable "pushgateway_url" {
  description = "Prometheus Pushgateway URL for pipeline metrics"
  type        = string
  default     = ""
}

variable "database_url" {
  description = "PostgreSQL connection string (stored in SSM SecureString)"
  type        = string
  sensitive   = true
  default     = "postgresql://admin:changeme@localhost:5432/dataops"
}

variable "vault_token" {
  description = "HashiCorp Vault token (stored in SSM SecureString)"
  type        = string
  sensitive   = true
  default     = ""
}
