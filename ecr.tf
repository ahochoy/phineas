resource "aws_ecr_repository" "api" {
  name                 = "phineas-api"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  encryption_configuration {
    encryption_type = "AES256"
  }
}

data "aws_iam_policy_document" "api_image_retrieval" {
  statement {
    sid    = "AllowLambdaImageRetrieval"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${data.aws_partition.current.partition}:lambda:us-east-2:${data.aws_caller_identity.current.account_id}:function:phineas-api"
      ]
    }
  }
}

resource "aws_ecr_repository_policy" "api_image_retrieval" {
  repository = aws_ecr_repository.api.name
  policy     = data.aws_iam_policy_document.api_image_retrieval.json
}
