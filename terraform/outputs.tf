output "data_lake_bucket" {
  description = "S3 data lake bucket name"
  value       = aws_s3_bucket.data_lake.bucket
}

output "ecr_repository_url" {
  description = "ECR repository URL for the pipeline image"
  value       = aws_ecr_repository.pipeline.repository_url
}

output "ecs_cluster_arn" {
  description = "ECS Fargate cluster ARN"
  value       = aws_ecs_cluster.pipeline.arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for pipeline logs"
  value       = aws_cloudwatch_log_group.pipeline.name
}

output "sns_alert_topic_arn" {
  description = "SNS topic ARN for pipeline alerts"
  value       = aws_sns_topic.alerts.arn
}
