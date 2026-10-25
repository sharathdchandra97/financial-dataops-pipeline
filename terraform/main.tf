terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state in S3 + DynamoDB locking (uncomment for production)
  # backend "s3" {
  #   bucket         = "your-terraform-state-bucket"
  #   key            = "dataops-pipeline/terraform.tfstate"
  #   region         = "eu-west-2"
  #   dynamodb_table = "terraform-lock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "financial-dataops-pipeline"
      Environment = var.environment
      ManagedBy   = "Terraform"
      Owner       = "platform-engineering"
    }
  }
}

# ─────────────────────────────────────────────────────────────────
# S3 Buckets
# ─────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "data_lake" {
  bucket = "${var.project_name}-data-lake-${var.environment}"
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket                  = aws_s3_bucket.data_lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle policy: move processed data to Intelligent-Tiering after 30 days
resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  rule {
    id     = "intelligent-tiering"
    status = "Enabled"
    transition {
      days          = 30
      storage_class = "INTELLIGENT_TIERING"
    }
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# ─────────────────────────────────────────────────────────────────
# ECR Repository (for pipeline Docker image)
# ─────────────────────────────────────────────────────────────────

resource "aws_ecr_repository" "pipeline" {
  name                 = "${var.project_name}-pipeline"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true   # Trivy-equivalent free scanning
  }
}

# ─────────────────────────────────────────────────────────────────
# ECS Fargate (serverless container execution)
# ─────────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "pipeline" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"   # Enables CloudWatch Container Insights
  }
}

resource "aws_ecs_task_definition" "pipeline" {
  family                   = "${var.project_name}-pipeline"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "pipeline"
      image     = "${aws_ecr_repository.pipeline.repository_url}:latest"
      essential = true
      environment = [
        { name = "PUSHGATEWAY_URL", value = var.pushgateway_url },
      ]
      secrets = [
        { name = "DATABASE_URL", valueFrom = aws_ssm_parameter.db_url.arn },
        { name = "VAULT_TOKEN",  valueFrom = aws_ssm_parameter.vault_token.arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.pipeline.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "pipeline"
        }
      }
    }
  ])
}

# ─────────────────────────────────────────────────────────────────
# CloudWatch Log Group
# ─────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/ecs/${var.project_name}-pipeline"
  retention_in_days = 30
}

# CloudWatch Alarm: pipeline errors > 0
resource "aws_cloudwatch_metric_alarm" "pipeline_errors" {
  alarm_name          = "${var.project_name}-pipeline-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "dataops_pipeline_pipeline_errors"
  namespace           = "DataOpsPipeline"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Triggers when the DataOps pipeline emits errors"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"
}

# ─────────────────────────────────────────────────────────────────
# SSM Parameter Store (secrets management)
# ─────────────────────────────────────────────────────────────────

resource "aws_ssm_parameter" "db_url" {
  name  = "/${var.project_name}/${var.environment}/DATABASE_URL"
  type  = "SecureString"
  value = var.database_url
}

resource "aws_ssm_parameter" "vault_token" {
  name  = "/${var.project_name}/${var.environment}/VAULT_TOKEN"
  type  = "SecureString"
  value = var.vault_token
}

# ─────────────────────────────────────────────────────────────────
# IAM Roles
# ─────────────────────────────────────────────────────────────────

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name               = "${var.project_name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task" {
  name               = "${var.project_name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "ecs_task_s3" {
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.data_lake.arn,
          "${aws_s3_bucket.data_lake.arn}/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = "*"
      }
    ]
  })
}
