resource "aws_dynamodb_table_item" "question_admission_control" {
  table_name = aws_dynamodb_table.sessions.name
  hash_key   = aws_dynamodb_table.sessions.hash_key
  range_key  = aws_dynamodb_table.sessions.range_key

  item = jsonencode({
    pk = {
      S = "CONTROL#QUESTION_ADMISSION"
    }
    sk = {
      S = "CONFIG"
    }
    schema_version = {
      S = "1"
    }
    enabled = {
      BOOL = var.demo_admissions_enabled
    }
  })
}
