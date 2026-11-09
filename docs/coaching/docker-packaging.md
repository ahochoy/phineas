# Docker packaging for FastAPI and Lambda

The image packages Python, locked production dependencies, the installed Phineas
package, and a Uvicorn startup command. ECR will store the image; Lambda will run
it. Terraform will manage those AWS resources separately from the image build.

AWS Lambda Web Adapter translates Lambda events into HTTP requests to Uvicorn.
It is copied into `/opt/extensions/`, where Lambda discovers extensions. Locally,
Docker starts Uvicorn directly; it does not automatically start Lambda extensions.
Thus the same image serves ordinary HTTP locally and is prepared for Lambda.
The local test validates HTTP behavior, not the Lambda event translation itself.

## Read the Dockerfile

- The `build` stage installs Python dependencies with `uv sync --locked --no-dev
  --no-editable`. A stale lockfile fails the build; tests, Moto, and Pyright are
  excluded. Non-editable installation puts the application into site-packages.
- The `runtime` stage copies only that environment and the adapter, leaving uv,
  build caches, and the project source tree outside the final image.
- The base Python version and tool/adapter tags are pinned. Tags are still mutable;
  production image references should use verified digests. ECR/Lambda will use a
  single-architecture image digest in the deployment slice.
- `.dockerignore` allowlists the build inputs. `.gitignore` alone does not protect
  the Docker context: without a separate rule Terraform state or `.aws` could be
  sent to the builder even if `COPY` never uses them.
- The application runs as numeric user 10001, listens on container port 8080,
  and disables access logs to avoid recording bearer IDs in URLs. It uses one
  Uvicorn process with no development reload.
- The adapter readiness probe uses `/health` and accepts only HTTP 200. It checks
  that the web process is running, not that AWS credentials or downstream services
  are configured.

## Build and run

The initial deployment target is Linux ARM64, matching the development machine.
Lambda's architecture must match the image. `--provenance=false` avoids attaching
an image index/attestation structure that can cause Lambda image-format rejection.

```bash
docker build --platform linux/arm64 --provenance=false -t phineas-api:local .
docker run --rm -p 127.0.0.1:8001:8080 phineas-api:local
```

Open http://127.0.0.1:8001/docs. Without AWS configuration, this container uses
in-memory synthetic sessions and skips narratives. Test sample creation, analysis,
and deletion; stop the foreground container with Ctrl-C.

`EXPOSE` documents the container port; `-p` publishes it to a host port. Binding
the host side to 127.0.0.1 keeps this local test off the external network.

## AWS configuration comes later

No credentials, Harness ARN, or table name are embedded in the image. Lambda will
receive table/Harness configuration through environment variables and short-lived
credentials through its execution role. Do not mount the host AWS directory or
copy login caches into the image for this exercise. The existing uv workflow
remains available for local tests against live AWS resources.

Before choosing the API Gateway configuration, resolve the timeout boundary:
our Harness call permits 60 seconds and the SDK read timeout is 90 seconds.
An API Gateway HTTP API has a 30-second integration limit. We must either bound
the synchronous generation path accordingly or introduce an asynchronous job
endpoint; increasing only the Lambda timeout will not fix that mismatch.

No public endpoint, ECR repository, or Lambda function is created by this slice.
Public deployment also requires throttling, concurrency limits, and proxy logging
controls before we expose model-generating routes.

References: [AWS Lambda Web Adapter](https://github.com/aws/aws-lambda-web-adapter),
[uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/).
