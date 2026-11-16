# Packaging the question worker

## Two entrypoints, shared application code

The API container runs Uvicorn and the Lambda Web Adapter. HTTP requests reach
FastAPI. The worker container instead uses the AWS Python Lambda runtime, which
receives an SQS event and calls `phineas.queue_worker.lambda_handler` directly.
There is no FastAPI route, HTTP listener in application code, or Web Adapter in
the worker. The base image's runtime emulator exposes a local-only invocation
endpoint for testing; that is not a deployed HTTP API.

`Dockerfile.worker` uses the AWS Python 3.14 base image and its built-in Runtime
Interface Client. Build and runtime stages share the same patched Amazon Linux
base, so compiled dependencies use a compatible OS/Python ABI. The API's Debian
venv must not be copied into the worker's Amazon Linux image.

The build stage installs the project and locked production dependencies with
`uv sync --locked --no-dev --no-editable`. The runtime copies installed packages
into `/var/task`, which the AWS Python runtime searches before bundled libraries.
That also makes the pinned SDK take precedence over the base image's SDK.
The worker keeps the AWS entrypoint and sets only its handler through `CMD`.
Lambda supplies the default least-privileged user; no AWS credentials are baked
into the image. The shared `.dockerignore` still allowlists only build inputs.

We retain the shared project dependency set for now. It includes unused HTTP
packages in the worker, but avoids a second lockfile/dependency graph during this
deployment slice. Split dependencies later only if image size or scan results
justify that additional maintenance.

## Build checkpoint

From the project root:

```sh
docker buildx build \
  --platform linux/arm64 \
  --provenance=false \
  --pull \
  --load \
  -f Dockerfile.worker \
  -t phineas-question-worker:local .
```

`--platform` matches the planned arm64 Lambda. `--provenance=false` avoids an
attestation-bearing manifest that Lambda cannot use. `--load` makes this
single-platform image available locally. `--pull` refreshes base images; those
tags can change, so the final ECR digest is what we will pin in Terraform.

Verify the image's imports and SDK capabilities without AWS credentials:

```sh
docker run --rm --platform linux/arm64 \
  --entrypoint /var/lang/bin/python3.14 \
  phineas-question-worker:local \
  -c 'import phineas.queue_worker, botocore.session; model = botocore.session.get_session().get_service_model("bedrock-agentcore"); assert "InvokeHarness" in model.operation_names; print("Worker imports and InvokeHarness model: passed")'
```

## Runtime-emulator smoke test

In one terminal:

```sh
docker run --rm --platform linux/arm64 \
  --name phineas-worker-smoke \
  -p 127.0.0.1:9001:8080 \
  -e PHINEAS_SESSIONS_TABLE=smoke-test-only \
  -e PHINEAS_HARNESS_ARN=smoke-test-only \
  -e AWS_REGION=us-east-2 \
  phineas-question-worker:local
```

In another terminal:

```sh
curl --fail-with-body -sS \
  http://127.0.0.1:9001/2015-03-31/functions/function/invocations \
  -H 'Content-Type: application/json' \
  -d '{"Records":[]}'
```

Expected response: `{"batchItemFailures":[]}`. Stop the foreground container
with Ctrl-C afterward. The configuration values above are deliberately fake;
empty batches create dependencies lazily and perform no AWS operations. Do not
mount your AWS directory or forward credentials for this smoke test.

This proves the native runtime can import and invoke the handler. It does not
prove SQS delivery, IAM permissions, DynamoDB persistence, or AgentCore access.
Those require the later deployed end-to-end test. Build, smoke-test, push, and
scan the worker image before selecting its deployment digest.

## Next infrastructure steps

Choose the ECR location and scope its Lambda image-retrieval policy for the worker.
If reusing the existing repository, give worker images distinct immutable tags
and do not replace the API's deployment digest. Then deploy the worker Lambda
with its dedicated role, a 120-second timeout, and the table/Harness environment.
Finally create a standard SQS event source mapping with batch size one,
`ReportBatchItemFailures`, and a deliberate concurrency cap. Enable API enqueue
configuration only when the consumer is ready.

## References

- [AWS Python Lambda container images, entrypoints, and local testing](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html)
