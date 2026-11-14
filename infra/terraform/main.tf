terraform {
  required_version = ">= 1.5"
}

# Staging skeleton only. Apply after a restore drill.
variable "region" { type = string }

resource "aws_db_instance" "proctor" {
  identifier                 = "phone-proctor-staging"
  engine                     = "postgres"
  engine_version             = "16"
  multi_az                   = true
  backup_retention_period    = 7
  deletion_protection        = true
  storage_encrypted          = true
  skip_final_snapshot        = false
  # PITR enabled via automated backups
}

resource "aws_s3_bucket" "evidence" {
  bucket = "phone-proctor-evidence-staging"
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "rpo_minutes" { value = 5 }
output "rto_minutes" { value = 30 }
