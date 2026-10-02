# Terraform and IAM: The Phineas AgentCore Execution Role

This note captures the mental model behind `iam.tf`. It is intended as a
review aid, not as a complete guide to AWS IAM.

## Start with the two questions

An AWS service role separates two security decisions:

1. **Who can assume the role?** The role's trust policy answers this.
2. **What can they do after assuming it?** The role's permissions policies
   answer this.

For Phineas, Amazon Bedrock AgentCore assumes the Harness execution role. AWS
Security Token Service (STS) then issues temporary credentials representing
that role. AgentCore uses those credentials to invoke Nova Micro and perform
the logging, tracing, image-pull, and metrics operations required by the
runtime.

```text
AgentCore Harness
    │
    │ sts:AssumeRole, allowed by the trust policy
    ▼
PhineasAgentCoreHarnessExecutionRole
    │
    │ temporary role credentials, limited by the permissions policy
    ▼
Bedrock · ECR Public · CloudWatch Logs · X-Ray · CloudWatch Metrics
```

The deploying human or automation is a third identity. It creates the role and
may need a narrowly scoped `iam:PassRole` permission when assigning the role to
AgentCore. `iam:PassRole` belongs to the deploying identity, not to the Harness
execution role.

## Terraform's four kinds of values

| Construct | Role | Phineas example |
| --- | --- | --- |
| `variable` | Input supplied to the configuration | Region or budget settings |
| `locals` | Named values calculated inside the configuration | Nova model ARNs |
| `data` | Read or calculate without managing a remote object | Current account ID or generated policy JSON |
| `resource` | Infrastructure Terraform creates and manages | IAM role and inline role policy |

The `aws_caller_identity` and `aws_partition` data sources query information
about the current AWS environment. They provide the account ID and partition
(`aws`, `aws-us-gov`, or `aws-cn`) used to build portable ARNs.

`aws_iam_policy_document` feels different because it does not retrieve an IAM
policy. It is a local document builder supplied by the AWS provider: Terraform
takes structured HCL statements and renders a JSON policy through its `.json`
attribute. That data source never appears as an object in the AWS console.

A data source is therefore better understood as a read-only or computed node
in Terraform's dependency graph than simply as a placeholder. It may query a
provider or calculate a value, but Terraform does not manage its lifecycle as
a remote resource.

Terraform references also create dependencies. When the inline policy refers
to `aws_iam_role.harness_execution.id`, Terraform knows the role must exist
before it can attach the policy.

## Expressions used in `iam.tf`

- `"${expression}"` embeds an expression in a string.
- `join(":", values)` turns a list of values into one colon-delimited string.
- `concat(list_a, list_b)` combines lists; it does not concatenate strings.
- `tostring(value)` converts a value to a string.

ARN means **Amazon Resource Name**. The inference profile ARN is assembled
from its partition, service, region, account, and resource components:

```text
arn:PARTITION:bedrock:REGION:ACCOUNT_ID:inference-profile/PROFILE_ID
```

Foundation-model ARNs omit an account ID because those models are owned by
AWS, while an inference-profile ARN includes the account using that profile.

## Part one: the trust policy

`data.aws_iam_policy_document.harness_assume_role` generates the role's trust
policy. Its only job is to determine who may obtain credentials for the role.

Its statement means:

> Allow the Bedrock AgentCore service to call `sts:AssumeRole`, but only when it
> is acting for an AgentCore Harness resource in this AWS account and region.

The fields have distinct jobs:

- `sid` is an optional **Statement ID** used as a readable label. It does not
  grant permission.
- `effect` is `Allow` or `Deny`.
- `actions` names the AWS API operation covered by the statement.
- `principals` identifies who may make the request. The service principal
  `bedrock-agentcore.amazonaws.com` represents AgentCore, not the developer.
- `conditions` add facts that must match before the statement applies.

The `aws:SourceAccount` and `aws:SourceArn` conditions are confused-deputy
protections. They prevent a Harness resource owned by another AWS customer
from causing AgentCore to use the Phineas role. `SourceAccount` must exactly
match the current account. `SourceArn` uses `ArnLike` because its Harness ID is
a wildcard, while the partition, service, region, account, and resource type
remain constrained.

The generated JSON becomes the role's trust policy here:

```hcl
resource "aws_iam_role" "harness_execution" {
  assume_role_policy = data.aws_iam_policy_document.harness_assume_role.json
}
```

## Part two: the permissions policy

`data.aws_iam_policy_document.harness_execution` generates the permissions
policy. It answers what AgentCore may do after assuming the role.

Each statement has one operational purpose:

| Statement | Why it exists |
| --- | --- |
| `InvokeNovaMicro` | Invoke the inference profile and the regional foundation models to which it may route |
| `PullAgentCoreManagedImage` | Request an ECR Public authorization token for the managed runtime image |
| `GetECRPublicBearerToken` | Ask STS for an ECR Public service bearer token |
| `WriteAgentCoreTraces` | Send runtime tracing and sampling data to X-Ray |
| `ManageAgentCoreRuntimeLogs` | Create or inspect the expected AgentCore log groups and streams |
| `WriteAgentCoreRuntimeLogs` | Write events to AgentCore runtime log streams |
| `DescribeLogGroups` | Discover relevant CloudWatch log groups |
| `ConfigureAgentCoreLogDelivery` | Configure the CloudWatch Logs resource policy used for delivery |
| `PublishAgentCoreMetrics` | Publish metrics only in the `bedrock-agentcore` namespace |

Some AWS APIs do not support resource-level authorization. Those statements
must use `resources = ["*"]`; their scope is reduced through narrow actions and,
where the service supports it, conditions. A wildcard is not automatically a
least-privilege failure, but it should always have a service-specific reason.

The resulting JSON is attached to the role as an inline policy:

```hcl
resource "aws_iam_role_policy" "harness_execution" {
  role   = aws_iam_role.harness_execution.id
  policy = data.aws_iam_policy_document.harness_execution.json
}
```

An inline policy is appropriate here because it belongs to one purpose-built
role. A customer-managed policy becomes more useful when multiple roles need
to share the same permissions or manage it independently.

## How IAM evaluates a request

A policy is a collection of independent statements. For a request, AWS checks
whether a statement matches the principal where applicable, action, resource,
and every condition in that statement.

The simplified result is:

1. An applicable explicit `Deny` wins.
2. Otherwise, an applicable `Allow` permits the request.
3. Otherwise, the request is implicitly denied.

All statements do not need to match together. The trust policy must first
allow AgentCore to assume the role; after assumption, the permissions policy
must allow each operation the temporary credentials attempt.

## Validation lessons

`terraform fmt` checks formatting and `terraform validate` checks Terraform's
configuration structure. Neither proves that every IAM action, condition key,
ARN, or runtime interaction is semantically correct.

For example, `aws.SourceAccount` can be valid Terraform syntax while being the
wrong IAM condition key; the correct key is `aws:SourceAccount`. Review the
rendered plan, use narrow runtime tests, and inspect authorization failures in
addition to running Terraform's local checks.

## A good sequence for the next unfamiliar integration

Before writing its full configuration:

1. State the one or two questions the component answers.
2. Draw the identities, data, or request flow in a few lines.
3. Identify the Terraform constructs that will represent each piece.
4. Implement one bounded section.
5. Format, validate, and explain what Terraform will create.
6. Add the next section only after the earlier mental model is clear.

This keeps the implementation and the learning synchronized instead of
postponing the conceptual explanation until after a large file is complete.
